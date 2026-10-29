"""Reusable, resettable, hashed invite links and the join transaction (D-21, D-22, D-23, UD-4).

The raw token is `base64url(HMAC-SHA256(INVITE_SECRET, invite.id))` cut to 32 characters
(192 bits), so the organiser can be shown the same link again while the database holds only
`sha256(raw)`. A reset revokes the live row and inserts the new one in one transaction under
the trip row lock, so there is never a moment when both links work. The raw token is never
logged: it travels only as a path parameter.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import math
import time
import uuid
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime

from fastapi import FastAPI, HTTPException, Request, status
from pydantic import BaseModel, SecretStr
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from trippilot.auth.models import Account
from trippilot.realtime.events import MEMBER_JOINED, append_trip_event
from trippilot.settings import Settings
from trippilot.trips.models import Invite, Member, Trip
from trippilot.trips.service import (
    ACTIVE_STATUS,
    MAX_MEMBERS,
    MEMBER_ROLE,
    count_active_members,
    lock_trip,
)

__all__ = [
    'Invite',
    'InviteError',
    'InvitePreview',
    'JoinResult',
    'SlidingWindowLimiter',
    'ensure_invite',
    'invite_rate_limit',
    'invite_url',
    'join_via_invite',
    'preview_invite',
    'raw_invite_token',
    'reset_invite',
    'resolve_invite',
]

TOKEN_LENGTH = 32
MAX_RAW_TOKEN_LENGTH = 128
RATE_LIMIT_REQUESTS = 10
RATE_LIMIT_WINDOW_SECONDS = 60.0
REMOVED_STATUS = 'removed'
LEFT_STATUS = 'left'

NOT_FOUND = 'not_found'
CLOSED = 'closed'
FULL = 'full'
REMOVED = 'removed'


class InviteError(HTTPException):
    """A refused invite request. `detail` (and `reason`) is a short machine-readable code.

    404 `not_found` covers an unknown, revoked or out-of-fence link; 409 carries `closed`,
    `full` or `removed`.
    """

    def __init__(self, status_code: int, reason: str) -> None:
        super().__init__(status_code, detail=reason)
        self.reason = reason


@dataclass(frozen=True)
class JoinResult:
    """Outcome of an accepted join: the trip, and whether the account was already in."""

    trip_id: uuid.UUID
    already_member: bool


class InvitePreview(BaseModel):
    """What the join page shows for a link (D-23).

    A signed-out visitor gets the trip name and the organiser's first name only. `trip_id` is set
    only for someone already in the trip, so the page can send them to it; a stranger never gets
    the id.
    """

    trip_name: str
    organiser_name: str
    members: list[str]
    joining_open: bool | None
    already_member: bool
    trip_id: uuid.UUID | None = None


def hash_invite_token(raw: str) -> bytes:
    """Return the sha256 digest under which a raw invite token is stored."""
    return hashlib.sha256(raw.encode()).digest()


def _raw_token(secret: SecretStr, invite_id: uuid.UUID) -> str:
    """Derive the raw token for an invite id from the server secret."""
    digest = hmac.new(secret.get_secret_value().encode(), invite_id.bytes, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip('=')[:TOKEN_LENGTH]


def raw_invite_token(settings: Settings, invite_id: uuid.UUID) -> str:
    """Return the raw token of an invite id, derived from the server secret and never stored.

    Log in with PayPal keeps only the invite id across the PayPal round trip (D-21) and uses this
    to join on return, so the raw token never enters PayPal's `state` or the database.
    """
    return _raw_token(settings.invite_secret, invite_id)


def invite_url(settings: Settings, invite: Invite) -> str:
    """Return the shareable `/join/<token>` URL for an invite."""
    token = _raw_token(settings.invite_secret, invite.id)
    return f'{settings.public_base_url.rstrip("/")}/join/{token}'


async def _active_invite(db: AsyncSession, trip_id: uuid.UUID) -> Invite | None:
    """Return the trip's live invite row, if it has one."""
    result = await db.execute(
        select(Invite).where(Invite.trip_id == trip_id, Invite.revoked_at.is_(None))
    )
    return result.scalar_one_or_none()


def _new_invite(settings: Settings, trip_id: uuid.UUID) -> Invite:
    """Build an invite row whose stored hash matches the token derived from its id."""
    invite_id = uuid.uuid4()
    raw = _raw_token(settings.invite_secret, invite_id)
    return Invite(id=invite_id, trip_id=trip_id, token_hash=hash_invite_token(raw))


async def ensure_invite(db: AsyncSession, trip: Trip, settings: Settings) -> Invite:
    """Return the trip's live invite, creating it on first request.

    Locks the trip row so two simultaneous first requests cannot both insert. The caller
    commits.
    """
    await lock_trip(db, trip.id)
    existing = await _active_invite(db, trip.id)
    if existing is not None:
        return existing
    invite = _new_invite(settings, trip.id)
    db.add(invite)
    await db.flush()
    return invite


async def reset_invite(db: AsyncSession, trip: Trip, settings: Settings) -> Invite:
    """Revoke the live link and create a new one in the caller's single transaction (D-21).

    The trip row lock serialises a reset against joins, which re-check the link under the same
    lock. The caller commits.
    """
    await lock_trip(db, trip.id)
    await db.execute(
        update(Invite)
        .where(Invite.trip_id == trip.id, Invite.revoked_at.is_(None))
        .values(revoked_at=func.now())
        .execution_options(synchronize_session=False)
    )
    invite = _new_invite(settings, trip.id)
    db.add(invite)
    await db.flush()
    return invite


async def resolve_invite(db: AsyncSession, raw: str) -> Invite | None:
    """Return the live invite for a raw token by its sha256, ignoring revoked rows."""
    if not raw or len(raw) > MAX_RAW_TOKEN_LENGTH:
        return None
    result = await db.execute(
        select(Invite).where(
            Invite.token_hash == hash_invite_token(raw), Invite.revoked_at.is_(None)
        )
    )
    return result.scalar_one_or_none()


def _fenced_out(account: Account | None, trip: Trip) -> bool:
    """Return True when a demo persona is looking at a non-demo trip (D-15)."""
    return account is not None and account.kind == 'persona' and not trip.demo_mode


def _first_name(display_name: str) -> str:
    """Return the first word of a display name, or the whole name when it has none."""
    parts = display_name.split()
    return parts[0] if parts else display_name


async def preview_invite(db: AsyncSession, raw: str, account: Account | None) -> InvitePreview:
    """Describe the trip behind a link for the join page.

    Raises 404 for an unknown or revoked link and for a persona on a non-demo trip.
    """
    invite = await resolve_invite(db, raw)
    trip = await db.get(Trip, invite.trip_id) if invite is not None else None
    if trip is None or _fenced_out(account, trip):
        raise InviteError(status.HTTP_404_NOT_FOUND, NOT_FOUND)
    organiser = await db.get(Account, trip.organiser_account_id)
    organiser_name = organiser.display_name if organiser is not None else ''
    if account is None:
        return InvitePreview(
            trip_name=trip.name,
            organiser_name=_first_name(organiser_name),
            members=[],
            joining_open=None,
            already_member=False,
        )
    rows = (
        await db.execute(
            select(Member.account_id, Account.display_name)
            .join(Account, Account.id == Member.account_id)
            .where(Member.trip_id == trip.id, Member.status == ACTIVE_STATUS)
            .order_by(Member.joined_at, Account.id)
        )
    ).all()
    already_member = any(member_id == account.id for member_id, _ in rows)
    return InvitePreview(
        trip_name=trip.name,
        organiser_name=organiser_name,
        members=[name for _, name in rows],
        joining_open=not trip.joining_closed and len(rows) < MAX_MEMBERS,
        already_member=already_member,
        trip_id=trip.id if already_member else None,
    )


async def join_via_invite(db: AsyncSession, raw: str, account: Account) -> JoinResult:
    """Make `account` an active member of the link's trip, once and within the cap.

    Locks the trip row, then re-checks the link under the lock (a reset may have revoked it
    while this call waited). Refusals: 404 unknown, revoked or out-of-fence link; 409 `removed`
    for a membership the organiser removed (UD-4: every link, old or reset, until the
    organiser re-adds them); 409 `closed`; 409 `full` at 12 active members (D-22). A left
    membership is reactivated. The caller commits.
    """
    invite = await resolve_invite(db, raw)
    if invite is None:
        raise InviteError(status.HTTP_404_NOT_FOUND, NOT_FOUND)
    trip = await lock_trip(db, invite.trip_id)
    if trip is None or await resolve_invite(db, raw) is None or _fenced_out(account, trip):
        raise InviteError(status.HTTP_404_NOT_FOUND, NOT_FOUND)
    membership = await db.get(Member, (trip.id, account.id), populate_existing=True)
    if membership is not None and membership.status == ACTIVE_STATUS:
        return JoinResult(trip_id=trip.id, already_member=True)
    if membership is not None and membership.status == REMOVED_STATUS:
        raise InviteError(status.HTTP_409_CONFLICT, REMOVED)
    if trip.joining_closed:
        raise InviteError(status.HTTP_409_CONFLICT, CLOSED)
    if await count_active_members(db, trip.id) >= MAX_MEMBERS:
        raise InviteError(status.HTTP_409_CONFLICT, FULL)
    if membership is None:
        db.add(Member(trip_id=trip.id, account_id=account.id, role=MEMBER_ROLE))
    else:
        membership.status = ACTIVE_STATUS
        membership.joined_at = datetime.now(UTC)
    await db.flush()
    await append_trip_event(
        db,
        trip.id,
        MEMBER_JOINED,
        {'account_id': str(account.id), 'display_name': account.display_name},
    )
    return JoinResult(trip_id=trip.id, already_member=False)


class SlidingWindowLimiter:
    """In-process sliding-window request counter keyed by client address."""

    def __init__(self, limit: int, window_seconds: float) -> None:
        self._limit = limit
        self._window = window_seconds
        self._hits: dict[str, deque[float]] = {}

    def check(self, key: str, now: float) -> float | None:
        """Record a hit; return None when allowed, or the seconds to wait when over the limit."""
        hits = self._hits.setdefault(key, deque())
        while hits and now - hits[0] >= self._window:
            hits.popleft()
        if len(hits) >= self._limit:
            return self._window - (now - hits[0])
        hits.append(now)
        return None

    def forget_idle(self, now: float) -> None:
        """Drop keys whose hits have all left the window, so the table cannot grow forever."""
        idle = [
            key for key, hits in self._hits.items() if not hits or now - hits[-1] >= self._window
        ]
        for key in idle:
            del self._hits[key]


def _limiter_for(app: FastAPI) -> SlidingWindowLimiter:
    """Return the app's invite limiter, creating it on first use (so every app has its own)."""
    limiter: SlidingWindowLimiter | None = getattr(app.state, 'invite_limiter', None)
    if limiter is None:
        limiter = SlidingWindowLimiter(RATE_LIMIT_REQUESTS, RATE_LIMIT_WINDOW_SECONDS)
        app.state.invite_limiter = limiter
    return limiter


def _client_key(request: Request) -> str:
    """Return the caller's address: the proxy-appended last X-Forwarded-For entry, else the peer.

    Behind Render's proxy the last entry is the one the proxy itself added, which a client
    cannot forge; with no proxy the TCP peer address is used.
    """
    forwarded = request.headers.get('x-forwarded-for', '')
    last = forwarded.rsplit(',', 1)[-1].strip()
    if last:
        return last
    return request.client.host if request.client is not None else 'unknown'


async def invite_rate_limit(request: Request) -> None:
    """FastAPI dependency: at most 10 invite requests per minute per client address (Pitfall 10).

    Tests that legitimately exceed it override this dependency through
    `app.dependency_overrides`.
    """
    limiter = _limiter_for(request.app)
    now = time.monotonic()
    limiter.forget_idle(now)
    retry_after = limiter.check(_client_key(request), now)
    if retry_after is not None:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            'Too many requests',
            headers={'Retry-After': str(max(1, math.ceil(retry_after)))},
        )

"""Opaque, DB-backed session tokens and the `tp_session` cookie (D-03).

The cookie carries a 256-bit random token. Only `sha256(token)` (32 bytes) is stored, so a
database read never yields a usable cookie (threat T-01-01). A session slides: activity more than
an hour after the last renewal moves `expires_at` to 30 days from now (D-03, ACC-04).
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import Response
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from trippilot.auth.models import SessionRow
from trippilot.settings import Settings

SESSION_COOKIE_NAME = 'tp_session'
SESSION_TTL = timedelta(days=30)
RENEW_AFTER = timedelta(hours=1)
"""Renewal is skipped when the session was renewed less than this long ago (limits writes)."""
_LOCAL_ENVIRONMENTS = frozenset({'local', 'test'})


def hash_token(raw: str) -> bytes:
    """Return the 32-byte sha256 digest under which a raw cookie value is stored."""
    return hashlib.sha256(raw.encode()).digest()


async def create_session(
    db: AsyncSession, account_id: uuid.UUID, *, is_persona: bool, user_agent: str | None
) -> str:
    """Insert a session row for the account and return the raw cookie value.

    The caller owns the transaction: the row is flushed, not committed. The raw value exists
    only in the return value; nothing but its hash is persisted.
    """
    raw = secrets.token_urlsafe(32)
    db.add(
        SessionRow(
            id_hash=hash_token(raw),
            account_id=account_id,
            expires_at=datetime.now(UTC) + SESSION_TTL,
            user_agent=user_agent,
            is_persona=is_persona,
        )
    )
    await db.flush()
    return raw


async def load_session(db: AsyncSession, raw: str) -> SessionRow | None:
    """Return the live session for a raw cookie value, or None if unknown or expired."""
    result = await db.execute(
        select(SessionRow).where(
            SessionRow.id_hash == hash_token(raw), SessionRow.expires_at > datetime.now(UTC)
        )
    )
    return result.scalar_one_or_none()


def touch_session(session: SessionRow, now: datetime | None = None) -> bool:
    """Slide a live session forward; return True when it was renewed.

    When the last renewal is over `RENEW_AFTER` old, `last_seen_at` becomes now and `expires_at`
    becomes now plus `SESSION_TTL`. The caller owns the transaction and, on True, re-issues the
    cookie so the browser's own expiry slides too.
    """
    moment = now if now is not None else datetime.now(UTC)
    if moment - session.last_seen_at < RENEW_AFTER:
        return False
    session.last_seen_at = moment
    session.expires_at = moment + SESSION_TTL
    return True


async def delete_session(db: AsyncSession, raw: str) -> None:
    """Delete the session for a raw cookie value (a no-op if there is none)."""
    await db.execute(delete(SessionRow).where(SessionRow.id_hash == hash_token(raw)))


async def delete_all_sessions(db: AsyncSession, account_id: uuid.UUID) -> None:
    """Delete every session of one account (sign out everywhere, D-10); others are untouched."""
    await db.execute(delete(SessionRow).where(SessionRow.account_id == account_id))


def cookie_secure(settings: Settings) -> bool:
    """Return True when cookies must carry the Secure flag (everywhere except local and test)."""
    return settings.app_env not in _LOCAL_ENVIRONMENTS


def set_session_cookie(response: Response, raw: str, settings: Settings) -> None:
    """Attach the session cookie: HttpOnly, SameSite=Lax, Secure outside local and test."""
    response.set_cookie(
        SESSION_COOKIE_NAME,
        raw,
        max_age=int(SESSION_TTL.total_seconds()),
        path='/',
        httponly=True,
        samesite='lax',
        secure=cookie_secure(settings),
    )


def clear_session_cookie(response: Response) -> None:
    """Send a clearing Set-Cookie (Max-Age=0) for the session cookie."""
    response.delete_cookie(SESSION_COOKIE_NAME, path='/', httponly=True, samesite='lax')

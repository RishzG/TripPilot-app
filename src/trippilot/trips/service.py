"""Trips: creation, the member-only view (D-20), My trips, membership controls (D-25, UD-4)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from trippilot.auth.models import Account
from trippilot.realtime.events import (
    MEMBER_JOINED,
    MEMBER_LEFT,
    MEMBER_REMOVED,
    TRIP_UPDATED,
    append_trip_event,
)
from trippilot.trips.models import Member, Trip

TRIP_NAME_MAX_LENGTH = 80
ORGANISER_ROLE = 'organiser'
MEMBER_ROLE = 'member'
ACTIVE_STATUS = 'active'
LEFT_STATUS = 'left'
REMOVED_STATUS = 'removed'
MAX_MEMBERS = 12
"""Hard cap on active members per trip (D-22)."""


class MemberView(BaseModel):
    """One member as shown on the trip page: who they are and how they look, nothing else.

    Whether a member saved PayPal is never part of this view (D-08); only the signed-in member
    can read their own status, from /api/paypal/vault/status.
    """

    account_id: uuid.UUID
    display_name: str
    nickname: str | None
    avatar_kind: str
    avatar_key: str | None
    role: str


class RemovedMemberView(BaseModel):
    """A member the organiser removed; shown only to the organiser, who can add them back."""

    account_id: uuid.UUID
    display_name: str


class TripView(BaseModel):
    """A trip as its members see it.

    `removed_members` is a list for the organiser and null for everyone else (UD-4).
    """

    id: uuid.UUID
    name: str = Field(min_length=1, max_length=TRIP_NAME_MAX_LENGTH)
    is_organiser: bool
    joining_closed: bool
    members: list[MemberView]
    removed_members: list[RemovedMemberView] | None = None


class TripSummary(BaseModel):
    """One row of My trips."""

    id: uuid.UUID
    name: str
    role: str
    member_count: int
    demo_mode: bool


class MemberStatus(BaseModel):
    """A membership after a leave, removal or readd."""

    account_id: uuid.UUID
    status: str


async def create_trip(db: AsyncSession, organiser: Account, name: str) -> Trip:
    """Insert a trip and its organiser membership in the caller's transaction (D-20).

    The trip is a demo trip when the organiser is a demo persona (D-15). The caller commits.
    """
    trip = Trip(
        name=name,
        organiser_account_id=organiser.id,
        demo_mode=organiser.kind == 'persona',
    )
    db.add(trip)
    await db.flush()
    db.add(Member(trip_id=trip.id, account_id=organiser.id, role=ORGANISER_ROLE))
    await db.flush()
    return trip


def _not_found() -> HTTPException:
    """Return the one 404 used for unknown trips and trips the caller is not in (IDOR guard)."""
    return HTTPException(status.HTTP_404_NOT_FOUND, 'Trip not found')


def _fenced_out(account: Account, trip: Trip) -> bool:
    """Return True when a demo persona is looking at a non-demo trip (D-15)."""
    return account.kind == 'persona' and not trip.demo_mode


async def _removed_members(db: AsyncSession, trip_id: uuid.UUID) -> list[RemovedMemberView]:
    """Return the trip's removed members, oldest membership first."""
    rows = (
        await db.execute(
            select(Member.account_id, Account.display_name)
            .join(Account, Account.id == Member.account_id)
            .where(Member.trip_id == trip_id, Member.status == REMOVED_STATUS)
            .order_by(Member.joined_at, Account.id)
        )
    ).all()
    return [RemovedMemberView(account_id=member_id, display_name=name) for member_id, name in rows]


async def get_trip_view(db: AsyncSession, trip_id: uuid.UUID, account: Account) -> TripView:
    """Return the trip for one of its active members.

    Raises 404, never 403, for a stranger and for an unknown id, so trip ids are not confirmed.
    """
    trip = await db.get(Trip, trip_id)
    if trip is None or _fenced_out(account, trip):
        raise _not_found()
    rows = (
        await db.execute(
            select(Member, Account)
            .join(Account, Account.id == Member.account_id)
            .where(Member.trip_id == trip_id, Member.status == ACTIVE_STATUS)
            .order_by(Member.joined_at, Account.id)
        )
    ).all()
    if not any(member.account_id == account.id for member, _ in rows):
        raise _not_found()
    is_organiser = trip.organiser_account_id == account.id
    return TripView(
        id=trip.id,
        name=trip.name,
        is_organiser=is_organiser,
        joining_closed=trip.joining_closed,
        removed_members=await _removed_members(db, trip_id) if is_organiser else None,
        members=[
            MemberView(
                account_id=member.account_id,
                display_name=who.display_name,
                nickname=who.nickname,
                avatar_kind=who.avatar_kind,
                avatar_key=who.avatar_key,
                role=member.role,
            )
            for member, who in rows
        ],
    )


async def lock_trip(db: AsyncSession, trip_id: uuid.UUID) -> Trip | None:
    """Return the trip with its row locked FOR UPDATE until the caller's transaction ends.

    Joins, readds, leaves, removals and link resets all take this lock first, so the member cap
    and the one-live-link rule are checked against a state nobody else can change meanwhile.
    """
    result = await db.execute(
        select(Trip)
        .where(Trip.id == trip_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return result.scalar_one_or_none()


async def count_active_members(db: AsyncSession, trip_id: uuid.UUID) -> int:
    """Return how many active members the trip has."""
    result = await db.execute(
        select(func.count())
        .select_from(Member)
        .where(Member.trip_id == trip_id, Member.status == ACTIVE_STATUS)
    )
    return int(result.scalar_one())


async def require_organiser_trip(
    db: AsyncSession, trip_id: uuid.UUID, account: Account, *, lock: bool = False
) -> Trip:
    """Return the trip when `account` is its organiser.

    Raises 404 for an unknown trip, a stranger and a persona looking at a non-demo trip (the
    id is never confirmed), and 403 for an active member who is not the organiser.
    """
    trip = await lock_trip(db, trip_id) if lock else await db.get(Trip, trip_id)
    if trip is None or _fenced_out(account, trip):
        raise _not_found()
    if trip.organiser_account_id == account.id:
        return trip
    membership = await db.get(Member, (trip_id, account.id))
    if membership is None or membership.status != ACTIVE_STATUS:
        raise _not_found()
    raise HTTPException(status.HTTP_403_FORBIDDEN, 'Only the organiser can do that')


async def list_trips(db: AsyncSession, account: Account) -> list[TripSummary]:
    """Return My trips: the account's active memberships, newest trip first.

    A persona sees demo trips only (D-15), whatever membership rows exist.
    """
    counts = (
        select(Member.trip_id, func.count().label('member_count'))
        .where(Member.status == ACTIVE_STATUS)
        .group_by(Member.trip_id)
        .subquery()
    )
    statement = (
        select(Trip, Member.role, counts.c.member_count)
        .join(Member, Member.trip_id == Trip.id)
        .join(counts, counts.c.trip_id == Trip.id)
        .where(Member.account_id == account.id, Member.status == ACTIVE_STATUS)
        .order_by(Trip.created_at.desc(), Trip.id)
    )
    if account.kind == 'persona':
        statement = statement.where(Trip.demo_mode.is_(True))
    rows = (await db.execute(statement)).all()
    return [
        TripSummary(
            id=trip.id,
            name=trip.name,
            role=role,
            member_count=int(member_count),
            demo_mode=trip.demo_mode,
        )
        for trip, role, member_count in rows
    ]


async def set_joining_closed(
    db: AsyncSession, trip_id: uuid.UUID, account: Account, *, closed: bool
) -> bool:
    """Close or reopen joining for new people (organiser only). The caller commits."""
    trip = await require_organiser_trip(db, trip_id, account, lock=True)
    trip.joining_closed = closed
    await db.flush()
    await append_trip_event(db, trip.id, TRIP_UPDATED, {'joining_closed': closed})
    return closed


async def leave_trip(db: AsyncSession, trip_id: uuid.UUID, account: Account) -> MemberStatus:
    """Mark the caller's membership `left` (D-25). The organiser cannot leave. Caller commits."""
    trip = await lock_trip(db, trip_id)
    if trip is None or _fenced_out(account, trip):
        raise _not_found()
    membership = await db.get(Member, (trip_id, account.id), populate_existing=True)
    if membership is None or membership.status != ACTIVE_STATUS:
        raise _not_found()
    if trip.organiser_account_id == account.id:
        raise HTTPException(status.HTTP_409_CONFLICT, 'The organiser cannot leave their own trip')
    membership.status = LEFT_STATUS
    await db.flush()
    await append_trip_event(db, trip_id, MEMBER_LEFT, {'account_id': str(account.id)})
    return MemberStatus(account_id=account.id, status=LEFT_STATUS)


async def remove_member(
    db: AsyncSession, trip_id: uuid.UUID, account: Account, member_id: uuid.UUID
) -> MemberStatus:
    """Mark a member `removed` (organiser only). The removal sticks (UD-4). Caller commits."""
    await require_organiser_trip(db, trip_id, account, lock=True)
    if member_id == account.id:
        raise HTTPException(status.HTTP_409_CONFLICT, 'The organiser cannot be removed')
    membership = await db.get(Member, (trip_id, member_id), populate_existing=True)
    if membership is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, 'Member not found')
    if membership.status != ACTIVE_STATUS:
        raise HTTPException(status.HTTP_409_CONFLICT, 'That person is not an active member')
    membership.status = REMOVED_STATUS
    await db.flush()
    await append_trip_event(db, trip_id, MEMBER_REMOVED, {'account_id': str(member_id)})
    return MemberStatus(account_id=member_id, status=REMOVED_STATUS)


async def readd_member(
    db: AsyncSession, trip_id: uuid.UUID, account: Account, member_id: uuid.UUID
) -> MemberStatus:
    """Make a removed member active again (organiser only, UD-4), within the cap. Caller commits.

    Locks the trip row like a join does, so the 12-member cap holds against concurrent joins.
    """
    await require_organiser_trip(db, trip_id, account, lock=True)
    membership = await db.get(Member, (trip_id, member_id), populate_existing=True)
    if membership is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, 'Member not found')
    if membership.status != REMOVED_STATUS:
        raise HTTPException(status.HTTP_409_CONFLICT, 'That person has not been removed')
    if await count_active_members(db, trip_id) >= MAX_MEMBERS:
        raise HTTPException(status.HTTP_409_CONFLICT, 'The trip is full')
    member = await db.get(Account, member_id)
    membership.status = ACTIVE_STATUS
    membership.joined_at = datetime.now(UTC)
    await db.flush()
    await append_trip_event(
        db,
        trip_id,
        MEMBER_JOINED,
        {
            'account_id': str(member_id),
            'display_name': member.display_name if member is not None else '',
            'readded': True,
        },
    )
    return MemberStatus(account_id=member_id, status=ACTIVE_STATUS)

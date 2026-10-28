"""Trip creation and the member-only trip view (D-20)."""

from __future__ import annotations

import uuid

from fastapi import HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from trippilot.auth.models import Account
from trippilot.trips.models import Member, Trip

TRIP_NAME_MAX_LENGTH = 80
ORGANISER_ROLE = 'organiser'
MEMBER_ROLE = 'member'
ACTIVE_STATUS = 'active'


class MemberView(BaseModel):
    """One member as shown on the trip page."""

    account_id: uuid.UUID
    display_name: str
    role: str


class TripView(BaseModel):
    """A trip as its members see it."""

    id: uuid.UUID
    name: str = Field(min_length=1, max_length=TRIP_NAME_MAX_LENGTH)
    is_organiser: bool
    members: list[MemberView]


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


async def get_trip_view(db: AsyncSession, trip_id: uuid.UUID, account: Account) -> TripView:
    """Return the trip for one of its active members.

    Raises 404, never 403, for a stranger and for an unknown id, so trip ids are not confirmed.
    """
    trip = await db.get(Trip, trip_id)
    if trip is None:
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
    return TripView(
        id=trip.id,
        name=trip.name,
        is_organiser=trip.organiser_account_id == account.id,
        members=[
            MemberView(
                account_id=member.account_id, display_name=who.display_name, role=member.role
            )
            for member, who in rows
        ],
    )

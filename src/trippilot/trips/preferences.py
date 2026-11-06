"""Travel preferences: explicit public projections and owner-only private fields.

Profiles belong to one trip membership, including demo personas, so editing one trip cannot
change another trip's preferences. Live events contain no profile values or owner identifier.
"""

from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from trippilot.auth.deps import CurrentAccount, DbSession
from trippilot.realtime.events import append_trip_event
from trippilot.trips.models import TravelProfile
from trippilot.trips.service import get_trip_view, lock_trip

router = APIRouter(prefix='/api/trips/{trip_id}/preferences', tags=['preferences'])
PREFERENCES_UPDATED = 'preferences.updated'
Pace = Literal['relaxed', 'balanced', 'active']


class TravelPreferences(BaseModel):
    """The caller's profile. Only the owner can read or replace these private fields."""

    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)

    origin: str = Field(default='', max_length=160)
    interests: str = Field(default='', max_length=1000)
    pace: Pace = 'balanced'
    budget_cents: int | None = Field(default=None, strict=True, ge=0, le=100_000_000)
    dietary_notes: str = Field(default='', max_length=1000)


class SharedTravelPreferences(BaseModel):
    """Allowlisted public fields; never serialize the private model to produce this view."""

    account_id: uuid.UUID
    display_name: str
    origin: str
    interests: str
    pace: Pace


class TripPreferences(BaseModel):
    """A private owner form and the active group's public preferences."""

    mine: TravelPreferences
    members: list[SharedTravelPreferences]


def own_preferences(profile: TravelProfile | None) -> TravelPreferences:
    """Return an owner's preferences or the same empty defaults before the first save."""
    if profile is None:
        return TravelPreferences()
    return TravelPreferences(
        origin=profile.origin,
        interests=profile.interests,
        pace=profile.pace,
        budget_cents=profile.budget_cents,
        dietary_notes=profile.dietary_notes,
    )


@router.get('')
async def read_preferences(
    trip_id: uuid.UUID, account: CurrentAccount, db: DbSession
) -> TripPreferences:
    """Return only active members' shared fields and the caller's private profile."""
    trip = await get_trip_view(db, trip_id, account)
    profiles = {
        row.account_id: row
        for row in (await db.scalars(select(TravelProfile).where(TravelProfile.trip_id == trip_id)))
    }
    shared = []
    for member in trip.members:
        profile = own_preferences(profiles.get(member.account_id))
        shared.append(
            SharedTravelPreferences(
                account_id=member.account_id,
                display_name=member.nickname or member.display_name,
                origin=profile.origin,
                interests=profile.interests,
                pace=profile.pace,
            )
        )
    return TripPreferences(mine=own_preferences(profiles.get(account.id)), members=shared)


@router.put('/me')
async def replace_preferences(
    trip_id: uuid.UUID, body: TravelPreferences, account: CurrentAccount, db: DbSession
) -> TripPreferences:
    """Replace only the caller's profile, serialized with membership mutations and retries."""
    await lock_trip(db, trip_id)
    await get_trip_view(db, trip_id, account)
    values = body.model_dump()
    statement = insert(TravelProfile).values(trip_id=trip_id, account_id=account.id, **values)
    await db.execute(
        statement.on_conflict_do_update(
            index_elements=['trip_id', 'account_id'],
            set_={**values, 'updated_at': statement.excluded.updated_at},
        )
    )
    await append_trip_event(db, trip_id, PREFERENCES_UPDATED, {})
    updated = await read_preferences(trip_id, account, db)
    await db.commit()
    return updated

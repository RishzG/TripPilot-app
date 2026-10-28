"""POST /api/trips and GET /api/trips/{trip_id}."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, status
from pydantic import BaseModel, Field

from trippilot.auth.deps import CurrentAccount, DbSession
from trippilot.trips.service import TRIP_NAME_MAX_LENGTH, TripView, create_trip, get_trip_view

router = APIRouter(prefix='/api/trips', tags=['trips'])


class CreateTripRequest(BaseModel):
    """Body of POST /api/trips: the organiser names the trip and nothing else (D-20)."""

    name: str = Field(min_length=1, max_length=TRIP_NAME_MAX_LENGTH)


class CreatedTrip(BaseModel):
    """Response of POST /api/trips."""

    id: uuid.UUID
    name: str


@router.post('', status_code=status.HTTP_201_CREATED)
async def start_trip(
    body: CreateTripRequest, account: CurrentAccount, db: DbSession
) -> CreatedTrip:
    """Start a trip; the signed-in account becomes its organiser and first member."""
    trip = await create_trip(db, account, body.name)
    created = CreatedTrip(id=trip.id, name=trip.name)
    await db.commit()
    return created


@router.get('/{trip_id}')
async def open_trip(trip_id: uuid.UUID, account: CurrentAccount, db: DbSession) -> TripView:
    """Return the trip to its members; 404 for anyone else."""
    return await get_trip_view(db, trip_id, account)

"""Trip routes: start and open a trip, the organiser's invite link, and the invite preview/join."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field

from trippilot.auth.deps import AppSettings, CurrentAccount, DbSession, OptionalAccount
from trippilot.trips.invites import (
    InvitePreview,
    ensure_invite,
    invite_rate_limit,
    invite_url,
    join_via_invite,
    preview_invite,
    reset_invite,
)
from trippilot.trips.service import (
    TRIP_NAME_MAX_LENGTH,
    TripView,
    create_trip,
    get_trip_view,
    require_organiser_trip,
)

router = APIRouter(tags=['trips'])


class CreateTripRequest(BaseModel):
    """Body of POST /api/trips: the organiser names the trip and nothing else (D-20)."""

    name: str = Field(min_length=1, max_length=TRIP_NAME_MAX_LENGTH)


class CreatedTrip(BaseModel):
    """Response of POST /api/trips."""

    id: uuid.UUID
    name: str


class InviteLink(BaseModel):
    """The organiser's invite link."""

    url: str


class JoinResponse(BaseModel):
    """Response of POST /api/invites/{token}/join."""

    trip_id: uuid.UUID
    already_member: bool


@router.post('/api/trips', status_code=status.HTTP_201_CREATED)
async def start_trip(
    body: CreateTripRequest, account: CurrentAccount, db: DbSession
) -> CreatedTrip:
    """Start a trip; the signed-in account becomes its organiser and first member."""
    trip = await create_trip(db, account, body.name)
    created = CreatedTrip(id=trip.id, name=trip.name)
    await db.commit()
    return created


@router.get('/api/trips/{trip_id}')
async def open_trip(trip_id: uuid.UUID, account: CurrentAccount, db: DbSession) -> TripView:
    """Return the trip to its members; 404 for anyone else."""
    return await get_trip_view(db, trip_id, account)


@router.get('/api/trips/{trip_id}/invite')
async def get_invite(
    trip_id: uuid.UUID, account: CurrentAccount, db: DbSession, settings: AppSettings
) -> InviteLink:
    """Return the trip's one reusable invite link, creating it on first request (organiser)."""
    trip = await require_organiser_trip(db, trip_id, account)
    invite = await ensure_invite(db, trip, settings)
    link = InviteLink(url=invite_url(settings, invite))
    await db.commit()
    return link


@router.post('/api/trips/{trip_id}/invite/reset')
async def reset_invite_link(
    trip_id: uuid.UUID, account: CurrentAccount, db: DbSession, settings: AppSettings
) -> InviteLink:
    """Kill the old link and issue a new one in one transaction (organiser)."""
    trip = await require_organiser_trip(db, trip_id, account)
    invite = await reset_invite(db, trip, settings)
    link = InviteLink(url=invite_url(settings, invite))
    await db.commit()
    return link


@router.get('/api/invites/{token}', tags=['invites'], dependencies=[Depends(invite_rate_limit)])
async def preview_invite_link(token: str, account: OptionalAccount, db: DbSession) -> InvitePreview:
    """Describe the trip behind an invite link; 404 for an unknown or revoked one."""
    return await preview_invite(db, token, account)


@router.post(
    '/api/invites/{token}/join', tags=['invites'], dependencies=[Depends(invite_rate_limit)]
)
async def join_invite_link(token: str, account: CurrentAccount, db: DbSession) -> JoinResponse:
    """Join the trip behind an invite link, once; see `join_via_invite` for the refusals."""
    result = await join_via_invite(db, token, account)
    response = JoinResponse(trip_id=result.trip_id, already_member=result.already_member)
    await db.commit()
    return response

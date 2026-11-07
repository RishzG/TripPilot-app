"""Manually authored itinerary drafts and server-calculated USD estimates."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select

from trippilot.auth.deps import CurrentAccount, DbSession
from trippilot.realtime.events import append_trip_event
from trippilot.trips.models import PlanVersion
from trippilot.trips.service import MAX_MEMBERS, get_trip_view, require_organiser_trip

router = APIRouter(prefix='/api/trips/{trip_id}/plans', tags=['plans'])


class PlanItemInput(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)

    id: uuid.UUID
    day: date
    title: str = Field(min_length=1, max_length=120)
    location: str = Field(max_length=160)
    estimated_cents: int | None = Field(strict=True, ge=0, le=100_000_000)
    participant_ids: list[uuid.UUID] = Field(min_length=1, max_length=MAX_MEMBERS)

    @model_validator(mode='after')
    def unique_participants(self) -> PlanItemInput:
        if len(set(self.participant_ids)) != len(self.participant_ids):
            raise ValueError('Each participant can appear only once per item')
        return self


class CreatePlanVersion(BaseModel):
    model_config = ConfigDict(extra='forbid')

    request_id: uuid.UUID
    base_version: int = Field(ge=0, le=2_147_483_647)
    items: list[PlanItemInput] = Field(max_length=60)

    @model_validator(mode='after')
    def unique_items(self) -> CreatePlanVersion:
        if len({item.id for item in self.items}) != len(self.items):
            raise ValueError('Each itinerary item must have a unique ID')
        return self


class EstimatedShare(BaseModel):
    account_id: uuid.UUID
    name: str
    cents: int | None


class PlanItem(PlanItemInput):
    shares: list[EstimatedShare]


class PlanSnapshot(BaseModel):
    currency: Literal['USD'] = 'USD'
    items: list[PlanItem]
    estimated_total_cents: int
    unpriced_items: int
    member_totals: list[EstimatedShare]


class PlanVersionView(PlanSnapshot):
    version: int
    created_at: datetime


class PlanView(BaseModel):
    draft: PlanVersionView | None


def _snapshot(items: list[PlanItemInput], names: dict[uuid.UUID, str]) -> PlanSnapshot:
    estimates: list[PlanItem] = []
    member_totals: dict[uuid.UUID, int | None] = {}
    total = unpriced = 0
    for item in sorted(items, key=lambda item: item.day):
        cents = item.estimated_cents
        quotient, remainder = divmod(cents or 0, len(item.participant_ids))
        if cents is None:
            unpriced += 1
        else:
            total += cents

        shares: list[EstimatedShare] = []
        # Give the leftover pennies to participants in stable ID order.
        for index, account_id in enumerate(sorted(item.participant_ids)):
            share = None if cents is None else quotient + int(index < remainder)
            shares.append(
                EstimatedShare(account_id=account_id, name=names[account_id], cents=share)
            )
            if share is not None:
                member_totals[account_id] = (member_totals.get(account_id) or 0) + share
            else:
                member_totals.setdefault(account_id, None)
        estimates.append(PlanItem(**item.model_dump(), shares=shares))

    return PlanSnapshot(
        items=estimates,
        estimated_total_cents=total,
        unpriced_items=unpriced,
        member_totals=[
            EstimatedShare(account_id=account_id, name=names[account_id], cents=cents)
            for account_id, cents in sorted(member_totals.items(), key=lambda pair: names[pair[0]])
        ],
    )


def _view(row: PlanVersion) -> PlanVersionView:
    return PlanVersionView.model_validate(
        {**row.snapshot, 'version': row.version, 'created_at': row.created_at}
    )


@router.get('')
async def get_plan(
    trip_id: uuid.UUID,
    account: CurrentAccount,
    db: DbSession,
    version: Annotated[int | None, Query(ge=1, le=2_147_483_647)] = None,
) -> PlanView:
    await get_trip_view(db, trip_id, account)
    statement = select(PlanVersion).where(PlanVersion.trip_id == trip_id)
    if version is None:
        row = await db.scalar(statement.order_by(PlanVersion.version.desc()).limit(1))
    else:
        row = await db.scalar(statement.where(PlanVersion.version == version))
        if row is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, 'Draft version not found')
    return PlanView(draft=_view(row) if row is not None else None)


@router.post('', status_code=status.HTTP_201_CREATED)
async def create_plan(
    trip_id: uuid.UUID, body: CreatePlanVersion, account: CurrentAccount, db: DbSession
) -> PlanVersionView:
    await require_organiser_trip(db, trip_id, account, lock=True)
    trip = await get_trip_view(db, trip_id, account)
    versions = select(PlanVersion).where(PlanVersion.trip_id == trip_id)
    existing = await db.scalar(versions.where(PlanVersion.request_id == body.request_id))
    if existing is not None:
        saved = _view(existing)
        submitted = sorted(body.items, key=lambda item: item.day)
        original = [
            PlanItemInput.model_validate(item.model_dump(exclude={'shares'}))
            for item in saved.items
        ]
        if submitted != original or body.base_version != saved.version - 1:
            raise HTTPException(status.HTTP_409_CONFLICT, 'Draft request ID already used')
        return saved

    latest = await db.scalar(
        select(PlanVersion.version)
        .where(PlanVersion.trip_id == trip_id)
        .order_by(PlanVersion.version.desc())
        .limit(1)
    )
    if body.base_version != (latest or 0):
        raise HTTPException(status.HTTP_409_CONFLICT, 'A newer draft is available')

    names = {member.account_id: member.nickname or member.display_name for member in trip.members}
    if any(account_id not in names for item in body.items for account_id in item.participant_ids):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, 'Select active trip members')
    row = PlanVersion(
        trip_id=trip_id,
        version=body.base_version + 1,
        request_id=body.request_id,
        snapshot=_snapshot(body.items, names).model_dump(mode='json'),
    )
    db.add(row)
    await db.flush()
    await append_trip_event(db, trip_id, 'plan.version_created', {})
    result = _view(row)
    await db.commit()
    return result

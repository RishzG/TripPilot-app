"""Manually authored itinerary drafts and server-calculated USD estimates."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

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


class ResearchSource(BaseModel):
    title: str
    url: str
    checked_on: date
    estimate_note: str


class PlanItem(PlanItemInput):
    shares: list[EstimatedShare]
    source: ResearchSource | None = None


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


def build_plan_item(
    item: PlanItemInput, names: dict[uuid.UUID, str], source: ResearchSource | None = None
) -> PlanItem:
    cents = item.estimated_cents
    quotient, remainder = divmod(cents or 0, len(item.participant_ids))
    # Give leftover pennies to participants in stable ID order.
    shares = [
        EstimatedShare(
            account_id=account_id,
            name=names[account_id],
            cents=None if cents is None else quotient + int(index < remainder),
        )
        for index, account_id in enumerate(sorted(item.participant_ids))
    ]
    return PlanItem(**item.model_dump(), shares=shares, source=source)


def _snapshot(items: list[PlanItem]) -> PlanSnapshot:
    estimates = sorted(items, key=lambda item: item.day)
    member_totals: dict[uuid.UUID, EstimatedShare] = {}
    total = unpriced = 0
    for item in estimates:
        if item.estimated_cents is None:
            unpriced += 1
        else:
            total += item.estimated_cents
        for share in item.shares:
            previous = member_totals.get(share.account_id)
            if previous is None:
                member_totals[share.account_id] = share
            elif share.cents is not None:
                member_totals[share.account_id] = previous.model_copy(
                    update={'cents': (previous.cents or 0) + share.cents}
                )

    return PlanSnapshot(
        items=estimates,
        estimated_total_cents=total,
        unpriced_items=unpriced,
        member_totals=sorted(member_totals.values(), key=lambda share: share.name),
    )


def plan_version_view(row: PlanVersion) -> PlanVersionView:
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
    return PlanView(draft=plan_version_view(row) if row is not None else None)


@router.post('', status_code=status.HTTP_201_CREATED)
async def create_plan(
    trip_id: uuid.UUID, body: CreatePlanVersion, account: CurrentAccount, db: DbSession
) -> PlanVersionView:
    await require_organiser_trip(db, trip_id, account, lock=True)
    trip = await get_trip_view(db, trip_id, account)
    versions = select(PlanVersion).where(PlanVersion.trip_id == trip_id)
    existing = await db.scalar(versions.where(PlanVersion.request_id == body.request_id))
    if existing is not None:
        saved = plan_version_view(existing)
        submitted = sorted(body.items, key=lambda item: item.day)
        original = [
            PlanItemInput.model_validate(item.model_dump(exclude={'shares', 'source'}))
            for item in saved.items
        ]
        if submitted != original or body.base_version != saved.version - 1:
            raise HTTPException(status.HTTP_409_CONFLICT, 'Draft request ID already used')
        return saved

    latest = await latest_plan(db, trip_id)
    if body.base_version != (latest.version if latest else 0):
        raise HTTPException(status.HTTP_409_CONFLICT, 'A newer draft is available')

    names = {member.account_id: member.nickname or member.display_name for member in trip.members}
    if any(account_id not in names for item in body.items for account_id in item.participant_ids):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, 'Select active trip members')
    previous_items = {item.id: item for item in plan_version_view(latest).items} if latest else {}
    sources = {}
    for item in body.items:
        previous = previous_items.get(item.id)
        if (
            previous
            and previous.source
            and (item.title, item.location, item.estimated_cents)
            == (previous.title, previous.location, previous.estimated_cents)
        ):
            sources[item.id] = previous.source
    result = await append_plan(db, trip_id, body, names, sources)
    await db.commit()
    return result


async def latest_plan(db: AsyncSession, trip_id: uuid.UUID) -> PlanVersion | None:
    return await db.scalar(
        select(PlanVersion)
        .where(PlanVersion.trip_id == trip_id)
        .order_by(PlanVersion.version.desc())
        .limit(1)
    )


async def append_plan(
    db: AsyncSession,
    trip_id: uuid.UUID,
    body: CreatePlanVersion,
    names: dict[uuid.UUID, str],
    sources: dict[uuid.UUID, ResearchSource],
) -> PlanVersionView:
    """Append a validated draft while the caller holds the trip lock."""
    items = [build_plan_item(item, names, sources.get(item.id)) for item in body.items]
    return await append_plan_items(db, trip_id, body.base_version + 1, body.request_id, items)


async def append_plan_items(
    db: AsyncSession,
    trip_id: uuid.UUID,
    version: int,
    request_id: uuid.UUID,
    items: list[PlanItem],
) -> PlanVersionView:
    """Append a version from calculated items under the trip lock."""
    row = PlanVersion(
        trip_id=trip_id,
        version=version,
        request_id=request_id,
        snapshot=_snapshot(items).model_dump(mode='json'),
    )
    db.add(row)
    await db.flush()
    await append_trip_event(db, trip_id, 'plan.version_created', {})
    return plan_version_view(row)

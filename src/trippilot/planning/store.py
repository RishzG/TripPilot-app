"""Trip-authorized projections, immutable inserts and private input boundaries."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime
from typing import Any

from fastapi import HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from trippilot.planning.domain import Draft, PlanItem, TripContext, shares


class PlanView(BaseModel):
    """Public itinerary and computed estimates; no private inputs or explanations."""

    id: uuid.UUID
    title: str
    sample: bool
    context_revision: int
    created_at: datetime
    items: list[PlanItem]
    shares: dict[str, dict[str, int]]
    totals: dict[str, int]
    total_cents: int
    current: bool


class RunView(BaseModel):
    """Safe lifecycle fields, never model responses or prompts."""

    id: uuid.UUID
    status: str
    plan_id: uuid.UUID | None
    error: str | None
    created_at: datetime


class ProposalView(BaseModel):
    """Version-bound affected-member responses and exact estimate deltas."""

    id: uuid.UUID
    base_id: uuid.UUID
    version_id: uuid.UUID
    cancelled_item_id: uuid.UUID
    affected: list[str]
    responses: dict[str, str]
    status: str
    cost_differences: dict[str, int]


async def context(db: AsyncSession, trip_id: uuid.UUID) -> TripContext:
    """Fetch the shared scheduling context after the caller checks access."""
    row = (
        (
            await db.execute(
                text("""SELECT name, destination, start_date, end_date,
        timezone, context_revision AS revision FROM trips WHERE id=:id"""),
                {'id': trip_id},
            )
        )
        .mappings()
        .one()
    )
    return TripContext.model_validate(dict(row))


async def inputs(
    db: AsyncSession, trip_id: uuid.UUID
) -> tuple[dict[str, Any], list[dict[str, Any]], str]:
    """Public research context and private per-member evaluation inputs stay separate.

    Private evaluation may only select existing public candidate IDs; its free text is
    returned exclusively to the member concerned. The public research call never sees it.
    """
    ctx = await context(db, trip_id)
    rows = (
        (
            await db.execute(
                text("""SELECT m.account_id, p.origin, p.interests, p.pace,
        p.budget_cents, p.dietary_notes, p.must_haves, p.preferred
        FROM members m LEFT JOIN travel_profiles p
        ON p.trip_id=m.trip_id AND p.account_id=m.account_id
        WHERE m.trip_id=:id AND m.status='active' ORDER BY m.account_id"""),
                {'id': trip_id},
            )
        )
        .mappings()
        .all()
    )
    concerns = (
        (
            await db.execute(
                text("""SELECT account_id, content FROM private_concerns
        WHERE trip_id=:id AND withdrawn_at IS NULL ORDER BY id"""),
                {'id': trip_id},
            )
        )
        .mappings()
        .all()
    )
    public = {
        'trip': ctx.model_dump(mode='json'),
        'members': [
            {
                key: str(row[key]) if key == 'account_id' else row[key]
                for key in ('account_id', 'origin', 'interests', 'pace')
            }
            for row in rows
        ],
    }
    private = [
        {
            'account_id': str(row['account_id']),
            'budget_cents': row['budget_cents'],
            'dietary_notes': row['dietary_notes'] or '',
            'must_haves': row['must_haves'] or '',
            'preferred': row['preferred'] or '',
            'concerns': [c['content'] for c in concerns if c['account_id'] == row['account_id']],
        }
        for row in rows
    ]
    fingerprint = hashlib.sha256(json.dumps([public, private], sort_keys=True).encode()).hexdigest()
    return public, private, fingerprint


def projection(row: Any, fingerprint: str) -> PlanView:
    """Compute rather than trust stored or model-generated financial totals."""
    items = [PlanItem.model_validate(item) for item in row['items']]
    allocated = {
        str(item.id): shares(item.total_cents, [str(p) for p in item.participants])
        for item in items
    }
    totals: dict[str, int] = {}
    for allocation in allocated.values():
        for member, cents in allocation.items():
            totals[member] = totals.get(member, 0) + cents
    return PlanView(
        id=row['id'],
        title=row['title'],
        sample=row['sample'],
        context_revision=row['context_revision'],
        created_at=row['created_at'],
        items=items,
        shares=allocated,
        totals=totals,
        total_cents=sum(i.total_cents for i in items),
        current=row['input_fingerprint'] == fingerprint,
    )


async def plan(db: AsyncSession, trip_id: uuid.UUID, plan_id: uuid.UUID) -> PlanView:
    """Always scope version lookups to the authorized trip."""
    row = (
        (
            await db.execute(
                text('SELECT * FROM plan_versions WHERE trip_id=:trip AND id=:id'),
                {'trip': trip_id, 'id': plan_id},
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise HTTPException(404, 'Plan version not found')
    _, _, fingerprint = await inputs(db, trip_id)
    return projection(row, fingerprint)


async def insert_plan(
    db: AsyncSession,
    trip_id: uuid.UUID,
    draft: Draft,
    *,
    sample: bool,
    revision: int,
    fingerprint: str,
) -> PlanView:
    """A new version is inserted once; existing versions are never updated."""
    row = (
        (
            await db.execute(
                text("""INSERT INTO plan_versions
        (trip_id,title,sample,context_revision,input_fingerprint,items)
        VALUES (:trip,:title,:sample,:revision,:fingerprint,CAST(:items AS jsonb)) RETURNING *"""),
                {
                    'trip': trip_id,
                    'title': draft.title,
                    'sample': sample,
                    'revision': revision,
                    'fingerprint': fingerprint,
                    'items': json.dumps([item.model_dump(mode='json') for item in draft.items]),
                },
            )
        )
        .mappings()
        .one()
    )
    return projection(row, fingerprint)

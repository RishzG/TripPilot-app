"""Private concerns: an author sees and withdraws their own; the leader sees text, never who.

Privacy rule (UD-2, UD-3): the leader's list of other members' concerns is built field by field
from an allowlist of `content` and the UTC calendar date. No account id, name, row id or client id
and no exact time is ever put in it. The leader's own concerns appear only in their own list
(`mine`), never in the anonymous one. The realtime event is a bare `concerns.changed` with
`{}`, so every viewer refetches its own projection. Nothing in this module logs concern
text or who wrote it.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from trippilot.auth.deps import CurrentAccount, DbSession
from trippilot.realtime.events import append_trip_event
from trippilot.trips.models import PrivateConcern
from trippilot.trips.service import get_trip_view, lock_trip

router = APIRouter(prefix='/api/trips/{trip_id}/concerns', tags=['concerns'])
CONCERNS_CHANGED = 'concerns.changed'
MAX_CONCERN_LENGTH = 1000
MAX_OPEN_CONCERNS = 20


class CreateConcern(BaseModel):
    """A client retains its UUID when retrying an ambiguous or failed send."""

    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)

    content: str = Field(min_length=1, max_length=MAX_CONCERN_LENGTH)
    client_concern_id: uuid.UUID


class OwnConcernView(BaseModel):
    """A concern as its author sees it. Never sent to anyone else."""

    id: int
    client_concern_id: uuid.UUID
    content: str
    created_at: datetime


class AnonymousConcernView(BaseModel):
    """A concern as the leader sees it: the text and the day, nothing else, ever (C-2)."""

    content: str
    submitted_on: date


class ConcernsView(BaseModel):
    """The caller's own open concerns, newest first.

    `anonymous` holds other members' open concerns for the leader (never the caller's own),
    newest first; it is null for everyone else.
    """

    mine: list[OwnConcernView]
    anonymous: list[AnonymousConcernView] | None


async def _concerns_view(
    db: AsyncSession, trip_id: uuid.UUID, account_id: uuid.UUID, *, is_organiser: bool
) -> ConcernsView:
    """Build the caller's projection from the open rows of the trip, newest first.

    The anonymous list skips rows the caller wrote, so a leader never sees their own concern
    presented as someone else's.
    """
    rows = list(
        await db.scalars(
            select(PrivateConcern)
            .where(PrivateConcern.trip_id == trip_id, PrivateConcern.withdrawn_at.is_(None))
            .order_by(PrivateConcern.created_at.desc(), PrivateConcern.id.desc())
        )
    )
    mine = [_own_view(row) for row in rows if row.account_id == account_id]
    anonymous = (
        [_anonymous_view(row) for row in rows if row.account_id != account_id]
        if is_organiser
        else None
    )
    return ConcernsView(mine=mine, anonymous=anonymous)


def _own_view(row: PrivateConcern) -> OwnConcernView:
    """Return the author's view of one open row."""
    return OwnConcernView(
        id=row.id,
        client_concern_id=row.client_concern_id,
        content=row.content or '',
        created_at=row.created_at,
    )


def _anonymous_view(row: PrivateConcern) -> AnonymousConcernView:
    """Return the leader's view of one open row, copied field by field from the allowlist."""
    return AnonymousConcernView(
        content=row.content or '',
        submitted_on=row.created_at.astimezone(UTC).date(),
    )


@router.get('')
async def list_concerns(trip_id: uuid.UUID, account: CurrentAccount, db: DbSession) -> ConcernsView:
    """Read the caller's own concerns, plus the anonymous list when the caller leads the trip."""
    trip = await get_trip_view(db, trip_id, account)
    return await _concerns_view(db, trip_id, account.id, is_organiser=trip.is_organiser)


@router.post('', status_code=status.HTTP_201_CREATED)
async def create_concern(
    trip_id: uuid.UUID, body: CreateConcern, account: CurrentAccount, db: DbSession
) -> OwnConcernView:
    """Save once, answer retries with the same row, and announce only the fact of a change."""
    await lock_trip(db, trip_id)
    await get_trip_view(db, trip_id, account)
    existing = await db.scalar(
        select(PrivateConcern).where(
            PrivateConcern.trip_id == trip_id,
            PrivateConcern.account_id == account.id,
            PrivateConcern.client_concern_id == body.client_concern_id,
        )
    )
    if existing is not None:
        if existing.withdrawn_at is not None:
            raise HTTPException(status.HTTP_409_CONFLICT, 'That concern was withdrawn')
        if existing.content != body.content:
            raise HTTPException(
                status.HTTP_409_CONFLICT, 'Concern ID already used for different text'
            )
        return _own_view(existing)
    open_count = await db.scalar(
        select(func.count())
        .select_from(PrivateConcern)
        .where(
            PrivateConcern.trip_id == trip_id,
            PrivateConcern.account_id == account.id,
            PrivateConcern.withdrawn_at.is_(None),
        )
    )
    if (open_count or 0) >= MAX_OPEN_CONCERNS:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f'You can have up to {MAX_OPEN_CONCERNS} open concerns. Withdraw one to add another.',
        )
    concern = PrivateConcern(
        trip_id=trip_id,
        account_id=account.id,
        client_concern_id=body.client_concern_id,
        content=body.content,
    )
    db.add(concern)
    await db.flush()
    await db.refresh(concern)
    await append_trip_event(db, trip_id, CONCERNS_CHANGED, {})
    result = _own_view(concern)
    await db.commit()
    return result


@router.post('/{concern_id}/withdraw')
async def withdraw_concern(
    trip_id: uuid.UUID,
    concern_id: Annotated[int, Path(ge=1, le=9_223_372_036_854_775_807)],
    account: CurrentAccount,
    db: DbSession,
) -> ConcernsView:
    """Erase the text of the caller's own concern; anyone else's id is a plain 404."""
    await lock_trip(db, trip_id)
    trip = await get_trip_view(db, trip_id, account)
    concern = await db.scalar(
        select(PrivateConcern).where(
            PrivateConcern.id == concern_id,
            PrivateConcern.trip_id == trip_id,
            PrivateConcern.account_id == account.id,
        )
    )
    if concern is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, 'Concern not found')
    if concern.withdrawn_at is None:
        concern.withdrawn_at = datetime.now(UTC)
        concern.content = None
        # An owner's historical explanation may paraphrase their concern. Withdraw those
        # derivatives too; private evaluation never places them in anyone else's notes.
        await db.execute(
            text("""DELETE FROM plan_private_notes WHERE account_id=:account
            AND plan_id IN (SELECT id FROM plan_versions WHERE trip_id=:trip)"""),
            {'account': account.id, 'trip': trip_id},
        )
        await db.flush()
        await append_trip_event(db, trip_id, CONCERNS_CHANGED, {})
    result = await _concerns_view(db, trip_id, account.id, is_organiser=trip.is_organiser)
    await db.commit()
    return result

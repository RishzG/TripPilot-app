"""Select an itinerary and agree a replacement without changing booking or payment state."""

from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from trippilot.auth.deps import CurrentAccount, DbSession
from trippilot.realtime.events import append_trip_event
from trippilot.trips.models import ActivityProposal, PlanVersion
from trippilot.trips.plans import (
    PlanItem,
    PlanItemInput,
    PlanVersionView,
    append_plan_items,
    build_plan_item,
    latest_plan,
    plan_version_view,
)
from trippilot.trips.service import TripView, get_trip_view, lock_trip, require_organiser_trip

router = APIRouter(prefix='/api/trips/{trip_id}/replanning', tags=['replanning'])
MAX_VERSION = 2_147_483_647


class SelectPlan(BaseModel):
    model_config = ConfigDict(extra='forbid')
    version: int = Field(ge=1, le=MAX_VERSION)


class ProposeReplacement(BaseModel):
    model_config = ConfigDict(extra='forbid')
    proposal_id: uuid.UUID
    base_version: int = Field(ge=1, le=MAX_VERSION)
    replacement: PlanItemInput


class ProposalResponse(BaseModel):
    model_config = ConfigDict(extra='forbid')
    revision: int = Field(ge=1, le=MAX_VERSION)
    action: Literal['accept', 'opt_out', 'withdraw']


class ProposalTerms(BaseModel):
    original: PlanItem
    replacement: PlanItem
    affected_ids: list[uuid.UUID]
    opted_out_ids: list[uuid.UUID]


class ProposalView(ProposalTerms):
    proposal_id: uuid.UUID
    revision: int
    base_version: int
    state: Literal['open', 'superseded', 'applied', 'withdrawn']
    accepted_ids: list[uuid.UUID]
    applied_version: int | None


class ReplanningView(BaseModel):
    proposal: ProposalView | None


def _item_input(item: PlanItem) -> PlanItemInput:
    return PlanItemInput.model_validate(item.model_dump(exclude={'shares', 'source'}))


def _view(row: ActivityProposal) -> ProposalView:
    return ProposalView.model_validate(
        {
            **row.terms,
            'proposal_id': row.proposal_id,
            'revision': row.revision,
            'base_version': row.base_version,
            'state': row.status,
            'accepted_ids': row.accepted,
            'applied_version': row.applied_version,
        }
    )


def _member_names(trip: TripView) -> dict[uuid.UUID, str]:
    return {member.account_id: member.nickname or member.display_name for member in trip.members}


async def _plan(db: AsyncSession, trip_id: uuid.UUID, version: int) -> PlanVersionView:
    plan = await db.get(PlanVersion, (trip_id, version))
    if plan is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, 'Plan version not found')
    return plan_version_view(plan)


async def _proposal(
    db: AsyncSession, trip_id: uuid.UUID, proposal_id: uuid.UUID | None = None
) -> ActivityProposal | None:
    statement = select(ActivityProposal).where(ActivityProposal.trip_id == trip_id)
    if proposal_id is not None:
        statement = statement.where(ActivityProposal.proposal_id == proposal_id)
    return await db.scalar(statement.order_by(ActivityProposal.id.desc()).limit(1))


@router.get('')
async def get_replanning(
    trip_id: uuid.UUID, account: CurrentAccount, db: DbSession
) -> ReplanningView:
    await get_trip_view(db, trip_id, account)
    proposal = await _proposal(db, trip_id)
    return ReplanningView(proposal=_view(proposal) if proposal else None)


@router.put('/current')
async def select_initial_plan(
    trip_id: uuid.UUID, body: SelectPlan, account: CurrentAccount, db: DbSession
) -> SelectPlan:
    trip = await require_organiser_trip(db, trip_id, account, lock=True)
    if trip.current_plan_version == body.version:
        return body
    if trip.current_plan_version is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, 'Use a replacement proposal to change the current plan'
        )
    selected = await _plan(db, trip_id, body.version)
    if not selected.items:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, 'Select a plan with at least one activity'
        )
    trip.current_plan_version = selected.version
    await append_trip_event(db, trip_id, 'trip.updated', {})
    await db.commit()
    return body


@router.post('/proposals', status_code=status.HTTP_201_CREATED)
async def propose_replacement(
    trip_id: uuid.UUID, body: ProposeReplacement, account: CurrentAccount, db: DbSession
) -> ProposalView:
    trip = await require_organiser_trip(db, trip_id, account, lock=True)
    retry = await _proposal(db, trip_id, body.proposal_id)
    if retry is not None:
        first = await db.scalar(
            select(ActivityProposal).where(
                ActivityProposal.trip_id == trip_id,
                ActivityProposal.proposal_id == body.proposal_id,
                ActivityProposal.revision == 1,
            )
        )
        if (
            first is None
            or first.base_version != body.base_version
            or (_item_input(_view(first).replacement) != body.replacement)
        ):
            raise HTTPException(status.HTTP_409_CONFLICT, 'Proposal ID already used')
        return _view(retry)
    latest = await _proposal(db, trip_id)
    if latest is not None and latest.status == 'open':
        raise HTTPException(status.HTTP_409_CONFLICT, 'Resolve the open replacement first')
    if trip.current_plan_version != body.base_version:
        raise HTTPException(
            status.HTTP_409_CONFLICT, 'The current plan changed. Review it and try again'
        )
    selected = await _plan(db, trip_id, body.base_version)
    original = next((item for item in selected.items if item.id == body.replacement.id), None)
    if original is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, 'Activity not found in the current plan')
    names = _member_names(await get_trip_view(db, trip_id, account))
    if not set(body.replacement.participant_ids) <= names.keys():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, 'Select active trip members')
    replacement = build_plan_item(body.replacement, names)
    affected = (set(original.participant_ids) | set(replacement.participant_ids)) & names.keys()
    proposal = ActivityProposal(
        trip_id=trip_id,
        proposal_id=body.proposal_id,
        revision=1,
        base_version=selected.version,
        status='open',
        accepted=[],
        terms=ProposalTerms(
            original=original,
            replacement=replacement,
            affected_ids=sorted(affected),
            opted_out_ids=[],
        ).model_dump(mode='json'),
    )
    db.add(proposal)
    await append_trip_event(db, trip_id, 'replanning.changed', {})
    await db.commit()
    return _view(proposal)


@router.post('/proposals/{proposal_id}/respond')
async def respond(
    trip_id: uuid.UUID,
    proposal_id: uuid.UUID,
    body: ProposalResponse,
    account: CurrentAccount,
    db: DbSession,
) -> ProposalView:
    trip = await lock_trip(db, trip_id)
    group = await get_trip_view(db, trip_id, account)
    if trip is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, 'Trip not found')
    row = await _proposal(db, trip_id, proposal_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, 'Replacement proposal not found')
    proposal = _view(row)
    if body.action == 'withdraw' and not group.is_organiser:
        raise HTTPException(status.HTTP_403_FORBIDDEN, 'Only the organiser can withdraw a proposal')
    if body.action == 'opt_out' and account.id in proposal.opted_out_ids:
        return proposal
    if proposal.revision != body.revision:
        raise HTTPException(status.HTTP_409_CONFLICT, 'Shares changed. Review the new revision')
    if (body.action == 'accept' and account.id in proposal.accepted_ids) or (
        body.action == 'withdraw' and row.status == 'withdrawn'
    ):
        return proposal
    if row.status != 'open' or trip.current_plan_version != proposal.base_version:
        raise HTTPException(status.HTTP_409_CONFLICT, 'This replacement is no longer open')

    if body.action == 'withdraw':
        row.status = 'withdrawn'
    else:
        if account.id not in proposal.affected_ids:
            raise HTTPException(status.HTTP_403_FORBIDDEN, 'Only affected members can respond')
        if not set(proposal.affected_ids) <= _member_names(group).keys():
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                'Membership changed. Ask the organiser to withdraw and re-propose',
            )
        if body.action == 'opt_out':
            row = await _opt_out(db, row, proposal, account.id)
        else:
            row.accepted = [*row.accepted, str(account.id)]
            if set(row.accepted) == {str(member_id) for member_id in proposal.affected_ids}:
                selected = await _plan(db, trip_id, proposal.base_version)
                latest = await latest_plan(db, trip_id)
                if latest is None:
                    raise RuntimeError('Selected itinerary is missing')
                items = [
                    proposal.replacement if item.id == proposal.original.id else item
                    for item in selected.items
                ]
                version = await append_plan_items(
                    db, trip_id, latest.version + 1, uuid.uuid4(), items
                )
                trip.current_plan_version = version.version
                row.applied_version = version.version
                row.status = 'applied'
                await append_trip_event(db, trip_id, 'trip.updated', {})
    await append_trip_event(db, trip_id, 'replanning.changed', {})
    await db.commit()
    return _view(row)


async def _opt_out(
    db: AsyncSession, row: ActivityProposal, proposal: ProposalView, account_id: uuid.UUID
) -> ActivityProposal:
    participants = proposal.replacement.participant_ids
    if account_id not in participants:
        raise HTTPException(
            status.HTTP_409_CONFLICT, 'You are already excluded from the replacement'
        )
    remaining = [participant for participant in participants if participant != account_id]
    replacement = proposal.replacement
    if remaining:
        item = _item_input(replacement)
        item.participant_ids = remaining
        names = {share.account_id: share.name for share in replacement.shares}
        replacement = build_plan_item(item, names)
    # With no participants left, close the proposal and retain the last offered terms.
    affected = (
        [member for member in proposal.affected_ids if member != account_id] if remaining else []
    )
    row.status = 'superseded'
    await db.flush()
    revised = ActivityProposal(
        trip_id=row.trip_id,
        proposal_id=row.proposal_id,
        revision=row.revision + 1,
        base_version=row.base_version,
        status='open' if remaining else 'withdrawn',
        accepted=[],
        terms=ProposalTerms(
            original=proposal.original,
            replacement=replacement,
            affected_ids=affected,
            opted_out_ids=[*proposal.opted_out_ids, account_id],
        ).model_dump(mode='json'),
    )
    db.add(revised)
    return revised

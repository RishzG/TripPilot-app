"""Membership-authorized planning APIs and explicit leader/member decisions."""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any, Literal

import psycopg
from fastapi import APIRouter, HTTPException
from procrastinate.exceptions import AlreadyEnqueued, ProcrastinateException
from pydantic import BaseModel, ConfigDict
from sqlalchemy import text

from trippilot.auth.deps import AppSettings, CurrentAccount, DbSession
from trippilot.planning import store
from trippilot.planning.domain import Draft, TripContext, validate_schedule
from trippilot.planning.sample import sample_plan
from trippilot.planning.tasks import run_pilot
from trippilot.realtime.events import append_trip_event
from trippilot.trips.service import get_trip_view, lock_trip, require_organiser_trip

log = logging.getLogger(__name__)
router = APIRouter(prefix='/api/trips/{trip_id}/planning', tags=['planning'])


class PlanningView(BaseModel):
    """Public plans plus only the caller's private explanations."""

    context: TripContext
    versions: list[store.PlanView]
    selected_id: uuid.UUID | None
    runs: list[store.RunView]
    proposals: list[store.ProposalView]
    my_explanations: dict[str, str]
    pilot_configured: bool


class Invocation(BaseModel):
    """Keep the same client UUID for ambiguous invocation retries."""

    model_config = ConfigDict(extra='forbid')
    client_id: uuid.UUID
    base_id: uuid.UUID | None = None
    cancelled_item_id: uuid.UUID | None = None


class Replacement(BaseModel):
    """Select an existing sourced candidate; no arbitrary model/price edits."""

    model_config = ConfigDict(extra='forbid')
    base_id: uuid.UUID
    cancelled_item_id: uuid.UUID
    candidate_version_id: uuid.UUID | None = None
    candidate_item_id: uuid.UUID | None = None
    opt_out: bool = False


class Response(BaseModel):
    """A response is bound to an immutable proposal version."""

    model_config = ConfigDict(extra='forbid')
    version_id: uuid.UUID
    response: Literal['accept', 'reject', 'discuss', 'alternative']


async def changed(db: DbSession, trip_id: uuid.UUID) -> None:
    """Publish only a change marker, in the same transaction as domain writes."""
    await append_trip_event(db, trip_id, 'planning.changed', {})
    await db.commit()


async def proposal_view(db: DbSession, trip_id: uuid.UUID, row: Any) -> store.ProposalView:
    """Calculate exact member deltas from immutable versions."""
    data = dict(row)
    base = await store.plan(db, trip_id, data['base_id'])
    version = await store.plan(db, trip_id, data['version_id'])
    return store.ProposalView(
        **{
            key: data[key]
            for key in (
                'id',
                'base_id',
                'version_id',
                'cancelled_item_id',
                'affected',
                'responses',
                'status',
            )
        },
        cost_differences={
            member: version.totals.get(member, 0) - base.totals.get(member, 0)
            for member in sorted(set(base.totals) | set(version.totals))
        },
    )


@router.get('')
async def read_planning(
    trip_id: uuid.UUID, account: CurrentAccount, db: DbSession, settings: AppSettings
) -> PlanningView:
    """Read the public domain and only the signed-in member's rationale."""
    await get_trip_view(db, trip_id, account)
    _, _, fingerprint = await store.inputs(db, trip_id)
    versions = (
        (
            await db.execute(
                text("""SELECT * FROM plan_versions WHERE trip_id=:trip
        ORDER BY created_at DESC,id"""),
                {'trip': trip_id},
            )
        )
        .mappings()
        .all()
    )
    runs = (
        (
            await db.execute(
                text("""SELECT * FROM pilot_runs WHERE trip_id=:trip
        ORDER BY created_at DESC LIMIT 20"""),
                {'trip': trip_id},
            )
        )
        .mappings()
        .all()
    )
    proposals = (
        (
            await db.execute(
                text("""SELECT * FROM plan_proposals WHERE trip_id=:trip
        ORDER BY created_at DESC"""),
                {'trip': trip_id},
            )
        )
        .mappings()
        .all()
    )
    notes = (
        (
            await db.execute(
                text("""SELECT n.plan_id,n.rationale FROM plan_private_notes n
        JOIN plan_versions p ON p.id=n.plan_id WHERE p.trip_id=:trip AND n.account_id=:account"""),
                {'trip': trip_id, 'account': account.id},
            )
        )
        .mappings()
        .all()
    )
    selected = await db.scalar(
        text('SELECT selected_plan_id FROM trips WHERE id=:trip'), {'trip': trip_id}
    )
    return PlanningView(
        context=await store.context(db, trip_id),
        versions=[store.projection(row, fingerprint) for row in versions],
        selected_id=selected,
        runs=[store.RunView.model_validate(dict(row)) for row in runs],
        proposals=[await proposal_view(db, trip_id, row) for row in proposals],
        my_explanations={str(row['plan_id']): row['rationale'] for row in notes},
        pilot_configured=bool(
            settings.ai_gateway_api_key.get_secret_value() and settings.pilot_model
        ),
    )


@router.put('/context')
async def edit_context(
    trip_id: uuid.UUID, body: TripContext, account: CurrentAccount, db: DbSession
) -> TripContext:
    """Only the leader edits scheduling context, with revision conflict detection."""
    await require_organiser_trip(db, trip_id, account, lock=True)
    current = await store.context(db, trip_id)
    if body.revision != current.revision:
        raise HTTPException(409, 'Trip details changed. Reload before saving.')
    await db.execute(
        text("""UPDATE trips SET name=:name,destination=:destination,
        start_date=:start_date,end_date=:end_date,timezone=:timezone,
        context_revision=context_revision+1 WHERE id=:id"""),
        {**body.model_dump(exclude={'revision'}), 'id': trip_id},
    )
    result = await store.context(db, trip_id)
    await append_trip_event(db, trip_id, 'trip.updated', {})
    await changed(db, trip_id)
    return result


@router.post('/sample', status_code=201)
async def create_sample(
    trip_id: uuid.UUID, account: CurrentAccount, db: DbSession
) -> list[store.PlanView]:
    """Create two illustrative versions once, without calling a paid provider."""
    from datetime import date, timedelta

    await require_organiser_trip(db, trip_id, account, lock=True)
    if await db.scalar(
        text('SELECT count(*) FROM plan_versions WHERE trip_id=:trip AND sample'), {'trip': trip_id}
    ):
        raise HTTPException(409, 'Sample versions already exist')
    trip = await get_trip_view(db, trip_id, account)
    ctx = await store.context(db, trip_id)
    _, _, fingerprint = await store.inputs(db, trip_id)
    versions = [
        await store.insert_plan(
            db,
            trip_id,
            sample_plan(
                ctx.start_date or date.today() + timedelta(days=14),
                [m.account_id for m in trip.members],
                alternative=alternative,
            ),
            sample=True,
            revision=ctx.revision,
            fingerprint=fingerprint,
        )
        for alternative in (False, True)
    ]
    await changed(db, trip_id)
    return versions


@router.post('/runs', status_code=202)
async def invoke(
    trip_id: uuid.UUID,
    body: Invocation,
    account: CurrentAccount,
    db: DbSession,
    settings: AppSettings,
) -> store.RunView:
    """Atomically queue one durable run; the worker's database poll survives restarts."""
    await require_organiser_trip(db, trip_id, account, lock=True)
    params = {'trip': trip_id, 'client': body.client_id}
    existing = (
        (
            await db.execute(
                text('SELECT * FROM pilot_runs WHERE trip_id=:trip AND client_id=:client'), params
            )
        )
        .mappings()
        .one_or_none()
    )
    if existing:
        if (
            existing['base_id'] != body.base_id
            or existing['cancelled_item_id'] != body.cancelled_item_id
        ):
            raise HTTPException(409, 'Request ID already used for another invocation')
        return store.RunView.model_validate(dict(existing))
    if not settings.ai_gateway_api_key.get_secret_value() or not settings.pilot_model:
        raise HTTPException(503, 'Pilot needs AI Gateway credentials and a configured model')
    ctx = await store.context(db, trip_id)
    if not ctx.destination or not ctx.start_date or not ctx.end_date:
        raise HTTPException(409, 'Set destination, dates and timezone before invoking Pilot')
    if bool(body.base_id) != bool(body.cancelled_item_id):
        raise HTTPException(422, 'Provide both a base version and cancelled item')
    if body.base_id:
        base = await store.plan(db, trip_id, body.base_id)
        selected = await db.scalar(
            text('SELECT selected_plan_id FROM trips WHERE id=:trip'), {'trip': trip_id}
        )
        if selected != base.id or not any(i.id == body.cancelled_item_id for i in base.items):
            raise HTTPException(409, 'Cancellation must refer to an item in the selected version')
    if await db.scalar(
        text(
            "SELECT count(*) FROM pilot_runs WHERE trip_id=:trip AND status IN ('queued','running')"
        ),
        {'trip': trip_id},
    ):
        raise HTTPException(409, 'Pilot is already working on this trip')
    row = (
        (
            await db.execute(
                text("""INSERT INTO pilot_runs
        (trip_id,client_id,context_revision,base_id,cancelled_item_id)
        VALUES (:trip,:client,:revision,:base,:item) RETURNING *"""),
                {
                    **params,
                    'revision': ctx.revision,
                    'base': body.base_id,
                    'item': body.cancelled_item_id,
                },
            )
        )
        .mappings()
        .one()
    )
    result = store.RunView.model_validate(dict(row))
    await changed(db, trip_id)
    try:
        await run_pilot.configure(queueing_lock=f'pilot:{trip_id}').defer_async(
            trip_id=str(trip_id)
        )
    except AlreadyEnqueued:
        # A start job for this trip is already waiting and will claim this run.
        pass
    except (ProcrastinateException, psycopg.Error):
        # The queued row is durable; dispatch_pilot picks it up within a minute.
        log.exception('could not defer the Pilot start job for trip %s', trip_id)
    return result


@router.post('/versions/{version_id}/select')
async def select_version(
    trip_id: uuid.UUID, version_id: uuid.UUID, account: CurrentAccount, db: DbSession
) -> store.PlanView:
    """Initial selection belongs to the leader; subsequent changes use proposals."""
    trip = await require_organiser_trip(db, trip_id, account, lock=True)
    selected = await db.scalar(
        text('SELECT selected_plan_id FROM trips WHERE id=:trip'), {'trip': trip_id}
    )
    version = await store.plan(db, trip_id, version_id)
    if selected == version_id:
        return version
    if selected is not None:
        raise HTTPException(409, 'Use an affected-member proposal to change the selected plan')
    if not version.current:
        raise HTTPException(409, 'Trip inputs changed. Generate a new version before selecting.')
    if version.sample and not trip.demo_mode:
        raise HTTPException(409, 'Sample plans are illustrations; only demo trips can select them')
    if await db.scalar(
        text('SELECT count(*) FROM plan_proposals WHERE version_id=:id'), {'id': version_id}
    ):
        raise HTTPException(409, 'Proposal versions require affected-member acceptance')
    await db.execute(
        text('UPDATE trips SET selected_plan_id=:id WHERE id=:trip'),
        {'id': version_id, 'trip': trip_id},
    )
    await changed(db, trip_id)
    return version


@router.post('/proposals', status_code=201)
async def propose(
    trip_id: uuid.UUID,
    body: Replacement,
    account: CurrentAccount,
    db: DbSession,
    settings: AppSettings,
) -> store.ProposalView:
    """Replace exactly one item, preserve all other IDs, and show per-person cost changes."""
    from trippilot.planning.pilot import PilotError, assess, save_notes

    await lock_trip(db, trip_id)
    await get_trip_view(db, trip_id, account)
    if not body.opt_out:
        await require_organiser_trip(db, trip_id, account)
    selected = await db.scalar(
        text('SELECT selected_plan_id FROM trips WHERE id=:trip'), {'trip': trip_id}
    )
    base = await store.plan(db, trip_id, body.base_id)
    cancelled = next((i for i in base.items if i.id == body.cancelled_item_id), None)
    if selected != base.id or cancelled is None:
        raise HTTPException(409, 'Choose an item in the selected plan')
    if body.opt_out:
        if body.candidate_version_id or body.candidate_item_id:
            raise HTTPException(422, 'An opt-out cannot replace the activity')
        remaining = [p for p in cancelled.participants if p != account.id]
        if len(remaining) == len(cancelled.participants):
            raise HTTPException(409, 'You are not participating in this activity')
        if not remaining:
            raise HTTPException(409, 'The last participant cannot opt out; propose a replacement')
        replacement = cancelled.model_copy(update={'participants': remaining})
    else:
        if not body.candidate_version_id or not body.candidate_item_id:
            raise HTTPException(422, 'Choose a candidate version and activity')
        candidate = await store.plan(db, trip_id, body.candidate_version_id)
        candidate_item = next((i for i in candidate.items if i.id == body.candidate_item_id), None)
        if candidate_item is None or base.sample != candidate.sample:
            raise HTTPException(409, 'Choose a compatible alternative')
        replacement = candidate_item
        if replacement.id in {i.id for i in base.items} or replacement.day != cancelled.day:
            raise HTTPException(409, 'Choose a different activity on the same day')
    draft = Draft(
        title=f'{"Opt-out" if body.opt_out else "Revision"}: {base.title}'[:160],
        items=[replacement if i.id == cancelled.id else i for i in base.items],
    )
    _, private, fingerprint = await store.inputs(db, trip_id)
    if not base.sample:
        try:
            validate_schedule(draft, await store.context(db, trip_id))
        except ValueError:
            raise HTTPException(409, 'This alternative conflicts with the trip schedule') from None
    await db.commit()
    try:
        import asyncio

        async with asyncio.timeout(210):
            notes = {} if base.sample else await assess(draft, private, settings)
    except PilotError as exc:
        raise HTTPException(409, str(exc)) from None
    except TimeoutError:
        raise HTTPException(503, 'Private constraint checking timed out; please retry') from None
    await lock_trip(db, trip_id)
    await get_trip_view(db, trip_id, account)
    if not body.opt_out:
        await require_organiser_trip(db, trip_id, account)
    _, _, fresh = await store.inputs(db, trip_id)
    now_selected = await db.scalar(
        text('SELECT selected_plan_id FROM trips WHERE id=:trip'), {'trip': trip_id}
    )
    if fingerprint != fresh or now_selected != base.id:
        raise HTTPException(409, 'Trip inputs changed while checking the alternative; try again')
    new = await store.insert_plan(
        db,
        trip_id,
        draft,
        sample=base.sample,
        revision=base.context_revision,
        fingerprint=fingerprint,
    )
    await save_notes(db, new.id, notes)
    affected = sorted({str(p) for p in cancelled.participants + replacement.participants})
    row = (
        (
            await db.execute(
                text("""INSERT INTO plan_proposals
        (trip_id,base_id,version_id,cancelled_item_id,affected)
        VALUES (:trip,:base,:version,:item,CAST(:affected AS jsonb)) RETURNING *"""),
                {
                    'trip': trip_id,
                    'base': base.id,
                    'version': new.id,
                    'item': cancelled.id,
                    'affected': json.dumps(affected),
                },
            )
        )
        .mappings()
        .one()
    )
    result = await proposal_view(db, trip_id, row)
    await changed(db, trip_id)
    return result


@router.post('/proposals/{proposal_id}/respond')
async def respond(
    trip_id: uuid.UUID,
    proposal_id: uuid.UUID,
    body: Response,
    account: CurrentAccount,
    db: DbSession,
) -> store.ProposalView:
    """Explicit rejection/discussion blocks finalization. Responses never transfer money."""
    await lock_trip(db, trip_id)
    await get_trip_view(db, trip_id, account)
    row = (
        (
            await db.execute(
                text('SELECT * FROM plan_proposals WHERE trip_id=:trip AND id=:id'),
                {'trip': trip_id, 'id': proposal_id},
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise HTTPException(404, 'Proposal not found')
    if row['status'] != 'open' or row['version_id'] != body.version_id:
        raise HTTPException(409, 'Proposal changed; review its current version')
    if str(account.id) not in row['affected']:
        raise HTTPException(403, 'Only affected members can respond')
    responses = {**row['responses'], str(account.id): body.response}
    updated = (
        (
            await db.execute(
                text("""UPDATE plan_proposals SET responses=CAST(:responses AS jsonb)
        WHERE id=:id RETURNING *"""),
                {'id': proposal_id, 'responses': json.dumps(responses)},
            )
        )
        .mappings()
        .one()
    )
    result = await proposal_view(db, trip_id, updated)
    await changed(db, trip_id)
    return result


@router.post('/proposals/{proposal_id}/finalize')
async def finalize(
    trip_id: uuid.UUID, proposal_id: uuid.UUID, account: CurrentAccount, db: DbSession
) -> store.ProposalView:
    """Compare base version and current inputs before applying unanimous acceptance."""
    await require_organiser_trip(db, trip_id, account, lock=True)
    row = (
        (
            await db.execute(
                text('SELECT * FROM plan_proposals WHERE trip_id=:trip AND id=:id'),
                {'trip': trip_id, 'id': proposal_id},
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise HTTPException(404, 'Proposal not found')
    if row['status'] == 'accepted':
        return await proposal_view(db, trip_id, row)
    selected = await db.scalar(
        text('SELECT selected_plan_id FROM trips WHERE id=:trip'), {'trip': trip_id}
    )
    version = await store.plan(db, trip_id, row['version_id'])
    if selected != row['base_id'] or not version.current:
        raise HTTPException(
            409, 'The selected plan or trip inputs changed; create a fresh proposal'
        )
    if any(row['responses'].get(member) != 'accept' for member in row['affected']):
        raise HTTPException(409, 'Every affected member must accept this exact revision')
    await db.execute(
        text('UPDATE trips SET selected_plan_id=:version WHERE id=:trip'),
        {'trip': trip_id, 'version': row['version_id']},
    )
    updated = (
        (
            await db.execute(
                text("UPDATE plan_proposals SET status='accepted' WHERE id=:id RETURNING *"),
                {'id': proposal_id},
            )
        )
        .mappings()
        .one()
    )
    result = await proposal_view(db, trip_id, updated)
    await changed(db, trip_id)
    return result

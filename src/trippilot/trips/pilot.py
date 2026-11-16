"""Authorised trip context and queued Pilot drafts."""

from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from trippilot.auth.deps import CurrentAccount, DbSession
from trippilot.auth.models import Account
from trippilot.db.engine import get_engine, session_factory
from trippilot.jobs.app import app
from trippilot.realtime.events import append_trip_event
from trippilot.trips.context import TripPlanningContext
from trippilot.trips.models import PilotRun, TripMessage
from trippilot.trips.pilot_research import research, supports_destination
from trippilot.trips.plans import CreatePlanVersion, PlanItemInput, append_plan, latest_plan
from trippilot.trips.service import get_trip_view, lock_trip, require_organiser_trip

router = APIRouter(prefix='/api/trips/{trip_id}', tags=['pilot'])
TASK_NAME = 'pilot.create_draft'


class PilotRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    request_id: uuid.UUID


class PilotRunView(BaseModel):
    id: uuid.UUID
    state: Literal['queued', 'running', 'ready', 'failed']
    draft_version: int | None
    message: str | None


class PilotView(BaseModel):
    run: PilotRunView | None


async def _latest_run(db: AsyncSession, trip_id: uuid.UUID) -> PilotRun | None:
    return await db.scalar(
        select(PilotRun)
        .where(PilotRun.trip_id == trip_id)
        .order_by(PilotRun.job_id.desc())
        .limit(1)
    )


async def _run_view(db: AsyncSession, run: PilotRun) -> PilotRunView:
    row = (
        await db.execute(
            text("""
                SELECT CASE WHEN j.status = 'doing'
                    AND (w.last_heartbeat IS NULL
                         OR w.last_heartbeat < now() - interval '2 minutes')
                    THEN 'stalled' ELSE j.status::text END AS job_state,
                    r.draft_version, r.failure
                FROM pilot_runs r
                LEFT JOIN procrastinate_jobs j ON j.id = r.job_id
                LEFT JOIN procrastinate_workers w ON w.id = j.worker_id
                WHERE r.id = :id AND r.trip_id = :trip_id
            """),
            {'id': run.id, 'trip_id': run.trip_id},
        )
    ).one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, 'Pilot run not found')
    state: Literal['queued', 'running', 'ready', 'failed']
    message = row.failure
    if row.draft_version is not None:
        state = 'ready'
    elif message is not None:
        state = 'failed'
    elif row.job_state in {'todo', 'doing'}:
        state = 'queued' if row.job_state == 'todo' else 'running'
    else:
        state = 'failed'
        message = 'Pilot stopped before saving a draft. You can start a new run.'
    return PilotRunView(id=run.id, state=state, draft_version=row.draft_version, message=message)


@router.put('/planning-context')
async def save_context(
    trip_id: uuid.UUID, body: TripPlanningContext, account: CurrentAccount, db: DbSession
) -> TripPlanningContext:
    trip = await require_organiser_trip(db, trip_id, account, lock=True)
    trip.planning_context = body.model_dump(mode='json')
    await append_trip_event(db, trip_id, 'trip.updated', {})
    await db.commit()
    return body


@router.get('/pilot')
async def get_pilot(trip_id: uuid.UUID, account: CurrentAccount, db: DbSession) -> PilotView:
    await get_trip_view(db, trip_id, account)
    run = await _latest_run(db, trip_id)
    return PilotView(run=await _run_view(db, run) if run else None)


@router.post('/pilot', status_code=status.HTTP_202_ACCEPTED)
async def start_pilot(
    trip_id: uuid.UUID, body: PilotRequest, account: CurrentAccount, db: DbSession
) -> PilotRunView:
    trip = await require_organiser_trip(db, trip_id, account, lock=True)
    same = await db.get(PilotRun, (body.request_id, trip_id))
    if same:
        return await _run_view(db, same)
    active = await _latest_run(db, trip_id)
    if active and (await _run_view(db, active)).state in {'queued', 'running'}:
        raise HTTPException(status.HTTP_409_CONFLICT, 'Pilot already has an active request')
    if trip.planning_context is None:
        raise HTTPException(status.HTTP_409_CONFLICT, 'Save trip details before starting Pilot')
    context = TripPlanningContext.model_validate(trip.planning_context)
    if not supports_destination(context.destination):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, 'The Pilot preview covers London'
        )
    latest = await latest_plan(db, trip_id)
    # Use the pinned queue schema's defer function on this transaction. Both rows commit together.
    job_id = await db.scalar(
        text("""
            SELECT (procrastinate_defer_jobs_v1(ARRAY[ROW(
                'pilot', :task, 0, NULL, NULL,
                jsonb_build_object('run_id', CAST(:run AS text), 'trip_id', CAST(:trip AS text)),
                NULL
            )::procrastinate_job_to_defer_v1]))[1]
        """),
        {'task': TASK_NAME, 'run': str(body.request_id), 'trip': str(trip_id)},
    )
    run = PilotRun(
        id=body.request_id,
        trip_id=trip_id,
        job_id=job_id,
        base_version=latest.version if latest else 0,
        planning_context=trip.planning_context,
    )
    db.add(run)
    await append_trip_event(db, trip_id, 'pilot.changed', {})
    result = PilotRunView(id=run.id, state='queued', draft_version=None, message=None)
    await db.commit()
    return result


@app.task(name=TASK_NAME, queue='pilot', retry=2)
async def create_pilot_draft(run_id: str, trip_id: str) -> None:
    get_engine()
    async with session_factory() as db:
        trip = await lock_trip(db, uuid.UUID(trip_id))
        if trip is None:
            return
        run = await db.get(PilotRun, (uuid.UUID(run_id), trip.id))
        if run is None or run.draft_version is not None or run.failure is not None:
            return
        latest_run = await _latest_run(db, trip.id)
        if latest_run is None or latest_run.id != run.id:
            return
        plan = await latest_plan(db, trip.id)
        if (plan.version if plan else 0) != run.base_version:
            run.failure = (
                'The itinerary changed during this run. Start Pilot again from the latest draft.'
            )
        elif trip.planning_context != run.planning_context:
            run.failure = (
                'Trip details changed during this run. Start Pilot again with the new details.'
            )
        else:
            account = await db.get(Account, trip.organiser_account_id)
            if account is None:
                raise RuntimeError('Trip organiser account is missing')
            group = await get_trip_view(db, trip.id, account)
            names = {
                member.account_id: member.nickname or member.display_name
                for member in group.members
            }
            messages = list(
                await db.scalars(
                    select(TripMessage.content)
                    .where(TripMessage.trip_id == trip.id)
                    .order_by(TripMessage.id.desc())
                    .limit(30)
                )
            )
            context = TripPlanningContext.model_validate(run.planning_context)
            items = []
            sources = {}
            for day, venue in research(context, messages):
                item = PlanItemInput(
                    id=uuid.uuid4(),
                    day=day,
                    title=venue.title,
                    location=venue.location,
                    estimated_cents=venue.estimate_cents,
                    participant_ids=list(names),
                )
                items.append(item)
                sources[item.id] = venue.source
            draft = await append_plan(
                db,
                trip.id,
                CreatePlanVersion(
                    request_id=uuid.uuid4(), base_version=run.base_version, items=items
                ),
                names,
                sources,
            )
            run.draft_version = draft.version
        await append_trip_event(db, trip.id, 'pilot.changed', {})
        await db.commit()

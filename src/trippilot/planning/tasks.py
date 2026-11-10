"""Durable database outbox polling, fenced leases and bounded Pilot execution."""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any

from sqlalchemy import text

from trippilot.db.engine import get_engine, session_factory
from trippilot.jobs.app import app
from trippilot.planning import store
from trippilot.planning.domain import TripContext, validate_schedule
from trippilot.planning.pilot import PilotError, assess_candidates, research, save_notes
from trippilot.realtime.events import append_trip_event
from trippilot.settings import get_settings
from trippilot.trips.service import lock_trip


async def process_next(trip_id: uuid.UUID | None = None) -> bool:
    """Claim one run; committed queued rows and expired leases survive process loss.

    Two attempts maximum, 300 seconds per execution, six-minute leases. The attempts
    value fences a stale worker from publishing after another worker reclaimed its run.
    When `trip_id` is given only that trip's runs are claimed; otherwise any trip's.
    """
    get_engine()
    async with session_factory() as db:
        row = (
            (
                await db.execute(
                    text("""SELECT * FROM pilot_runs
            WHERE (status='queued' OR (status='running' AND lease_until < now()))
            AND (CAST(:trip AS uuid) IS NULL OR trip_id=CAST(:trip AS uuid))
            ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT 1"""),
                    {'trip': trip_id},
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            return False
        run = dict(row)
        if run['attempts'] >= 2:
            await db.execute(
                text("UPDATE pilot_runs SET status='failed',error=:error WHERE id=:id"),
                {
                    'id': run['id'],
                    'error': 'Pilot was interrupted twice. Please start a new request.',
                },
            )
            await append_trip_event(db, run['trip_id'], 'planning.changed', {})
            await db.commit()
            return True
        attempt = run['attempts'] + 1
        await db.execute(
            text("""UPDATE pilot_runs SET status='running', attempts=:attempt,
            lease_until=now()+interval '6 minutes' WHERE id=:id"""),
            {'id': run['id'], 'attempt': attempt},
        )
        await append_trip_event(db, run['trip_id'], 'planning.changed', {})
        await db.commit()
    error: str | None = None
    usage: dict[str, Any] = {}
    try:
        async with asyncio.timeout(300):
            async with session_factory() as db:
                trip = await lock_trip(db, run['trip_id'])
                if trip is None:
                    return True
                public, private, fingerprint = await store.inputs(db, run['trip_id'])
                if public['trip']['revision'] != run['context_revision']:
                    raise PilotError(
                        'Trip details changed before Pilot started. Start a fresh request.'
                    )
                if run['base_id']:
                    base = await store.plan(db, run['trip_id'], run['base_id'])
                    cancelled = next(i for i in base.items if i.id == run['cancelled_item_id'])
                    public['cancellation'] = cancelled.model_dump(mode='json')
                    public['remaining_itinerary'] = [
                        i.model_dump(mode='json') for i in base.items if i.id != cancelled.id
                    ]
                await db.commit()
            candidates, usage = await research(public, get_settings())
            draft, notes = await assess_candidates(candidates, private, get_settings())
            validate_schedule(
                draft, TripContext.model_validate(public['trip']), complete=not bool(run['base_id'])
            )
            async with session_factory() as db:
                await lock_trip(db, run['trip_id'])
                current = (
                    (
                        await db.execute(
                            text('SELECT * FROM pilot_runs WHERE id=:id FOR UPDATE'),
                            {'id': run['id']},
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if (
                    current is None
                    or current['attempts'] != attempt
                    or current['status'] != 'running'
                ):
                    return True
                _, _, fresh_fingerprint = await store.inputs(db, run['trip_id'])
                if fingerprint != fresh_fingerprint:
                    raise PilotError(
                        'Trip inputs changed while Pilot was working. Please start a fresh request.'
                    )
                version = await store.insert_plan(
                    db,
                    run['trip_id'],
                    draft,
                    sample=False,
                    revision=run['context_revision'],
                    fingerprint=fingerprint,
                )
                await save_notes(db, version.id, notes)
                await db.execute(
                    text("""UPDATE pilot_runs SET status='completed',plan_id=:plan,
                    lease_until=NULL,usage=CAST(:usage AS jsonb) WHERE id=:id"""),
                    {'plan': version.id, 'id': run['id'], 'usage': json.dumps(usage)},
                )
                await append_trip_event(db, run['trip_id'], 'planning.changed', {})
                await db.commit()
    except PilotError as exc:
        error = str(exc)
    except TimeoutError:
        error = 'Pilot reached its time limit. Try a shorter trip or a narrower request.'
    except Exception:
        # No exception body or traceback: validation errors may contain private model text.
        error = 'Pilot could not validate a complete draft. Please retry.'
    if error:
        async with session_factory() as db:
            result = await db.execute(
                text("""UPDATE pilot_runs SET status='failed',error=:error,
                lease_until=NULL WHERE id=:id AND attempts=:attempt
                AND status='running' RETURNING id"""),
                {'id': run['id'], 'attempt': attempt, 'error': error},
            )
            if result.scalar_one_or_none() is not None:
                await append_trip_event(db, run['trip_id'], 'planning.changed', {})
            await db.commit()
    return True


@app.task(name='planning.run_pilot')
async def run_pilot(trip_id: str) -> None:
    """Start one queued run for this trip right away; `dispatch_pilot` stays the backup."""
    await process_next(uuid.UUID(trip_id))


@app.periodic(cron='* * * * *')
@app.task(queueing_lock='pilot_dispatch')
async def dispatch_pilot(timestamp: int) -> None:
    """The existing worker checks the transactional outbox every minute."""
    for _ in range(3):
        if not await process_next():
            break

"""One LISTEN connection per web process, bridging Postgres NOTIFY to the in-process hub.

`append_trip_event` sends `pg_notify('trip_events', <row id>)` inside the writer's transaction,
so a notification exists only for a committed row. The listener re-reads the row by id and
publishes it. The connection is dedicated and plain psycopg (never the pooler: LISTEN needs a
session-level connection, Pitfall 9). On any connection loss it reconnects with backoff and then
tells every open stream to re-read, because notifications sent while it was down are gone.

psycopg's `notifies()` holds the connection lock for the whole `async for` body, so nothing
there may touch the connection: the loop only queues ids, and a second task loads the rows
through the shared SQLAlchemy engine and publishes them in order.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Callable

import psycopg
import structlog
from sqlalchemy.exc import SQLAlchemyError

from trippilot.db.engine import get_engine, session_factory
from trippilot.jobs.app import libpq_conninfo
from trippilot.realtime.hub import StreamEvent, TripHub
from trippilot.realtime.models import TripEvent

LISTENER_APPLICATION_NAME = 'trippilot-listener'
"""Shown in `pg_stat_activity`, so the connection is easy to find (and to kill in tests)."""

IDLE_TICK_SECONDS = 5.0
"""How long one `notifies()` pass lasts before the loop checks `stop` and probes the connection."""

INITIAL_BACKOFF_SECONDS = 0.25
MAX_BACKOFF_SECONDS = 10.0

log = structlog.get_logger(__name__)

_LISTEN_STATEMENT = 'LISTEN trip_events'  # the channel `append_trip_event` notifies


async def load_event(event_id: int) -> StreamEvent | None:
    """Return the stored event with this id, or None when there is no such row."""
    get_engine()
    async with session_factory() as session:
        row = await session.get(TripEvent, event_id)
        return StreamEvent.from_row(row) if row is not None else None


async def _publish_ids(pending: asyncio.Queue[str], hub: TripHub) -> None:
    """Turn queued notification payloads into published events, in arrival order."""
    while True:
        raw_id = await pending.get()
        try:
            event = await load_event(int(raw_id))
        except ValueError:
            log.warning('trip_events_bad_notification', payload=raw_id[:40])
            continue
        except (SQLAlchemyError, OSError) as error:
            # The event is not lost: every open stream re-reads the table from its own cursor.
            log.warning('trip_events_load_failed', error=type(error).__name__)
            hub.resync_all()
            continue
        if event is not None:
            hub.publish(event.trip_id, event)


async def _listen_once(
    dsn: str, hub: TripHub, stop: asyncio.Event, on_listening: Callable[[], None]
) -> None:
    """Hold one LISTEN connection until it fails or `stop` is set."""
    pending: asyncio.Queue[str] = asyncio.Queue()
    async with await psycopg.AsyncConnection.connect(
        dsn, autocommit=True, application_name=LISTENER_APPLICATION_NAME
    ) as conn:
        await conn.execute(_LISTEN_STATEMENT)
        log.info('trip_events_listening')
        on_listening()
        # Anything committed while there was no connection produced no notification we saw.
        hub.resync_all()
        publisher = asyncio.create_task(_publish_ids(pending, hub), name='trip-events-publisher')
        try:
            while not stop.is_set():
                async for notice in conn.notifies(timeout=IDLE_TICK_SECONDS):
                    pending.put_nowait(notice.payload)
                await conn.execute('SELECT 1')  # raises if the server went away silently
        finally:
            publisher.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await publisher


async def run_listener(dsn: str, hub: TripHub, stop: asyncio.Event) -> None:
    """Bridge `trip_events` notifications to `hub` until `stop` is set, surviving disconnects."""
    backoff = INITIAL_BACKOFF_SECONDS

    def listening() -> None:
        nonlocal backoff
        backoff = INITIAL_BACKOFF_SECONDS

    while not stop.is_set():
        try:
            await _listen_once(dsn, hub, stop, listening)
        except (psycopg.Error, OSError) as error:
            log.warning('trip_events_listener_lost', error=type(error).__name__)
        if stop.is_set():
            return
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=backoff)
        backoff = min(backoff * 2, MAX_BACKOFF_SECONDS)


def listener_dsn(database_url: str) -> str:
    """Return the libpq connection string for the dedicated LISTEN connection."""
    return libpq_conninfo(database_url)

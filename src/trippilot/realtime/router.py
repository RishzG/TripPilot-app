"""GET /api/trips/{trip_id}/events: the trip's live event stream (D-24), with replay.

Order of operations, which is what makes reconnects exact (RESEARCH Pattern 5, Pitfall 7):
subscribe to the hub first, then replay stored rows after `Last-Event-ID`, then drain live
events, skipping every id already sent. A row that commits between the subscribe and the replay
is seen twice and sent once.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterable, AsyncIterator
from dataclasses import dataclass
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request
from fastapi.sse import EventSourceResponse, ServerSentEvent
from sqlalchemy import func, select

from trippilot.auth.deps import CurrentAccount, DbSession
from trippilot.db.engine import get_engine, session_factory
from trippilot.realtime.events import MEMBER_LEFT, MEMBER_REMOVED
from trippilot.realtime.hub import Signal, StreamEvent, TripHub
from trippilot.realtime.models import TripEvent
from trippilot.trips.service import get_trip_view

router = APIRouter(prefix='/api', tags=['realtime'])

_ENDS_OWN_STREAM = frozenset({MEMBER_LEFT, MEMBER_REMOVED})
"""Event types that, when they name the viewer, end that viewer's stream."""


@dataclass(frozen=True, slots=True)
class StreamAccess:
    """Who may read which trip's stream, decided before the first byte is sent."""

    trip_id: uuid.UUID
    account_id: uuid.UUID


async def stream_access(trip_id: uuid.UUID, account: CurrentAccount, db: DbSession) -> StreamAccess:
    """Authorise the stream: 401 signed out, 404 unless the caller is an active member.

    This runs as a dependency so the refusal is a normal HTTP error; once the stream has
    started, errors can no longer change the status code. The request's database session is
    released here so a stream that lives for minutes does not hold a pooled connection.
    """
    await get_trip_view(db, trip_id, account)
    access = StreamAccess(trip_id=trip_id, account_id=account.id)
    await db.rollback()
    return access


def trip_hub(request: Request) -> TripHub:
    """Return the process-wide hub the LISTEN bridge publishes to."""
    hub: TripHub = request.app.state.trip_hub
    return hub


async def _events_after(trip_id: uuid.UUID, floor: int) -> list[StreamEvent]:
    """Return the trip's stored events with id above `floor`, oldest first."""
    get_engine()
    async with session_factory() as session:
        rows = (
            (
                await session.execute(
                    select(TripEvent)
                    .where(TripEvent.trip_id == trip_id, TripEvent.id > floor)
                    .order_by(TripEvent.id)
                )
            )
            .scalars()
            .all()
        )
    return [StreamEvent.from_row(row) for row in rows]


async def _latest_event_id(trip_id: uuid.UUID) -> int:
    """Return the id of the trip's newest stored event, or 0 when it has none."""
    get_engine()
    async with session_factory() as session:
        latest = await session.scalar(
            select(func.max(TripEvent.id)).where(TripEvent.trip_id == trip_id)
        )
    return int(latest or 0)


def _as_sse(event: StreamEvent) -> ServerSentEvent:
    """Encode a stored event; the row id is the SSE id the browser sends back on reconnect."""
    return ServerSentEvent(data=event.payload, event=event.type, id=str(event.id))


def _ends_stream_of(event: StreamEvent, account_id: uuid.UUID) -> bool:
    """Return True when the event says the viewer left or was removed from the trip."""
    return event.type in _ENDS_OWN_STREAM and event.payload.get('account_id') == str(account_id)


async def _stream(
    access: StreamAccess, hub: TripHub, last_event_id: int | None
) -> AsyncIterator[ServerSentEvent]:
    """Yield `ready`, the replay, then live events, until the viewer is out or falls behind."""
    sent: set[int] = set()
    async with hub.subscribe(access.trip_id) as queue:
        # Flushes the headers and tells clients (and tests) the subscription is in place.
        yield ServerSentEvent(comment='ready')
        floor = (
            last_event_id if last_event_id is not None else await _latest_event_id(access.trip_id)
        )

        async def catch_up() -> AsyncIterator[StreamEvent]:
            for event in await _events_after(access.trip_id, floor):
                if event.id not in sent:
                    sent.add(event.id)
                    yield event

        if last_event_id is not None:
            async for event in catch_up():
                yield _as_sse(event)
                if _ends_stream_of(event, access.account_id):
                    return
        while True:
            message = await queue.get()
            if message is Signal.DROPPED:
                return
            if message is Signal.RESYNC:
                async for event in catch_up():
                    yield _as_sse(event)
                    if _ends_stream_of(event, access.account_id):
                        return
                continue
            if message.id in sent:
                continue
            sent.add(message.id)
            yield _as_sse(message)
            if _ends_stream_of(message, access.account_id):
                return


@router.get('/trips/{trip_id}/events', response_class=EventSourceResponse)
async def trip_events(
    access: Annotated[StreamAccess, Depends(stream_access)],
    hub: Annotated[TripHub, Depends(trip_hub)],
    last_event_id: Annotated[int | None, Header(ge=0)] = None,
) -> AsyncIterable[ServerSentEvent]:
    """Stream the trip's events to its members; reconnecting with Last-Event-ID replays the gap."""
    async for item in _stream(access, hub, last_event_id):
        yield item

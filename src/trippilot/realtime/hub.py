"""In-process fan-out of trip events to the open event streams of one web process.

The LISTEN bridge (`listener.py`) publishes every committed `trip_events` row here; each open
stream holds a bounded queue. A consumer that cannot keep up is dropped, not waited for: its
stream ends and the browser reconnects with `Last-Event-ID`, which replays what it missed.
"""

from __future__ import annotations

import asyncio
import enum
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from trippilot.realtime.models import TripEvent

DEFAULT_QUEUE_SIZE = 64
"""Events one stream may have waiting before it is considered too slow and dropped."""


@dataclass(frozen=True, slots=True)
class StreamEvent:
    """One committed `trip_events` row, as streamed to members."""

    id: int
    trip_id: uuid.UUID
    type: str
    payload: dict[str, Any]

    @classmethod
    def from_row(cls, row: TripEvent) -> StreamEvent:
        """Build the streamed form of a stored `trip_events` row."""
        return cls(id=row.id, trip_id=row.trip_id, type=row.type, payload=dict(row.payload))


class Signal(enum.Enum):
    """Control messages a stream receives besides events."""

    RESYNC = 'resync'
    """The LISTEN connection was (re)established: events may have been missed, so re-read."""

    DROPPED = 'dropped'
    """This subscriber fell behind and was removed: end the stream so the client reconnects."""


Message = StreamEvent | Signal


class TripHub:
    """Per-trip sets of bounded queues, one queue per open stream."""

    def __init__(self, queue_size: int = DEFAULT_QUEUE_SIZE) -> None:
        self._queue_size = queue_size
        self._subscribers: dict[uuid.UUID, set[asyncio.Queue[Message]]] = {}

    @asynccontextmanager
    async def subscribe(self, trip_id: uuid.UUID) -> AsyncIterator[asyncio.Queue[Message]]:
        """Register a queue for the trip's events for the length of the `async with` block."""
        queue: asyncio.Queue[Message] = asyncio.Queue(maxsize=self._queue_size)
        self._subscribers.setdefault(trip_id, set()).add(queue)
        try:
            yield queue
        finally:
            self._discard(trip_id, queue)

    def subscriber_count(self, trip_id: uuid.UUID | None = None) -> int:
        """Return how many streams are subscribed to one trip, or to any trip."""
        if trip_id is not None:
            return len(self._subscribers.get(trip_id, ()))
        return sum(len(queues) for queues in self._subscribers.values())

    def publish(self, trip_id: uuid.UUID, event: StreamEvent) -> None:
        """Hand the event to every stream of that trip; drop streams whose queue is full."""
        for queue in tuple(self._subscribers.get(trip_id, ())):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                self._drop(trip_id, queue)

    def resync_all(self) -> None:
        """Tell every stream to re-read its trip from the database (after a LISTEN reconnect)."""
        for trip_id, queues in tuple(self._subscribers.items()):
            for queue in tuple(queues):
                try:
                    queue.put_nowait(Signal.RESYNC)
                except asyncio.QueueFull:
                    self._drop(trip_id, queue)

    def _drop(self, trip_id: uuid.UUID, queue: asyncio.Queue[Message]) -> None:
        """Remove a slow subscriber and leave a DROPPED marker as the only thing it will read."""
        self._discard(trip_id, queue)
        while not queue.empty():
            queue.get_nowait()
        queue.put_nowait(Signal.DROPPED)

    def _discard(self, trip_id: uuid.UUID, queue: asyncio.Queue[Message]) -> None:
        """Forget a queue, and the trip's entry once nobody is subscribed."""
        queues = self._subscribers.get(trip_id)
        if queues is None:
            return
        queues.discard(queue)
        if not queues:
            del self._subscribers[trip_id]

"""TripHub fan-out: per-trip delivery, slow-consumer drop, resync (plan 01-09)."""

from __future__ import annotations

import asyncio
import uuid

from trippilot.realtime.hub import Message, Signal, StreamEvent, TripHub


def _event(event_id: int, trip_id: uuid.UUID) -> StreamEvent:
    return StreamEvent(id=event_id, trip_id=trip_id, type='member.joined', payload={})


async def _drain(queue: asyncio.Queue[Message]) -> list[Message]:
    items: list[Message] = []
    while not queue.empty():
        items.append(queue.get_nowait())
    return items


async def test_publish_reaches_only_subscribers_of_that_trip() -> None:
    hub = TripHub()
    mine, other = uuid.uuid4(), uuid.uuid4()
    async with hub.subscribe(mine) as mine_queue, hub.subscribe(other) as other_queue:
        hub.publish(mine, _event(1, mine))

        assert await _drain(mine_queue) == [_event(1, mine)]
        assert await _drain(other_queue) == []


async def test_leaving_the_block_unsubscribes() -> None:
    hub = TripHub()
    trip = uuid.uuid4()
    async with hub.subscribe(trip):
        assert hub.subscriber_count(trip) == 1
    assert hub.subscriber_count() == 0


async def test_a_full_queue_is_dropped_and_told_to_reconnect() -> None:
    hub = TripHub(queue_size=2)
    trip = uuid.uuid4()
    async with hub.subscribe(trip) as slow, hub.subscribe(trip) as quick:
        for number in range(1, 4):
            hub.publish(trip, _event(number, trip))
            await _drain(quick)

        assert hub.subscriber_count(trip) == 1
        assert await _drain(slow) == [Signal.DROPPED]


async def test_resync_all_signals_every_open_stream() -> None:
    hub = TripHub()
    first, second = uuid.uuid4(), uuid.uuid4()
    async with hub.subscribe(first) as one, hub.subscribe(second) as two:
        hub.resync_all()

        assert await _drain(one) == [Signal.RESYNC]
        assert await _drain(two) == [Signal.RESYNC]

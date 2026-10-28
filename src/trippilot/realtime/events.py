"""Trip events: the rows the live member list streams (D-24).

`append_trip_event` writes the row and the NOTIFY inside the caller's transaction, so a
subscriber is woken only when the change is committed and never for a rolled-back one.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from trippilot.realtime.models import TripEvent

MEMBER_JOINED = 'member.joined'
MEMBER_LEFT = 'member.left'
MEMBER_REMOVED = 'member.removed'
TRIP_UPDATED = 'trip.updated'

TRIP_EVENTS_CHANNEL = 'trip_events'


async def append_trip_event(
    db: AsyncSession, trip_id: uuid.UUID, event_type: str, payload: dict[str, Any]
) -> int:
    """Insert a `trip_events` row and `pg_notify` its id in the caller's transaction.

    Only the id is sent: a NOTIFY payload is limited to 8000 bytes, and the listener re-reads
    the row. The caller commits. Returns the new event id.
    """
    event = TripEvent(trip_id=trip_id, type=event_type, payload=payload)
    db.add(event)
    await db.flush()
    await db.execute(
        text('SELECT pg_notify(:channel, :event_id)'),
        {'channel': TRIP_EVENTS_CHANNEL, 'event_id': str(event.id)},
    )
    return event.id

"""ORM model for the 0003_invites_events `trip_events` table."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, ForeignKey, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from trippilot.db.base import Base


class TripEvent(Base):
    """One thing that happened on a trip. The id is what the SSE stream replays from."""

    __tablename__ = 'trip_events'

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    trip_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey('trips.id', ondelete='CASCADE')
    )
    type: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    created_at: Mapped[datetime] = mapped_column(server_default=text('now()'))

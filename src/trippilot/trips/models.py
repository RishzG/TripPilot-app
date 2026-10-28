"""ORM models for the 0001_skeleton trip tables: trips and members."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from trippilot.db.base import Base


class Trip(Base):
    """A trip. `demo_mode` is true for trips started by a demo persona (D-15)."""

    __tablename__ = 'trips'

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text('gen_random_uuid()')
    )
    name: Mapped[str] = mapped_column(Text)
    organiser_account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey('accounts.id')
    )
    demo_mode: Mapped[bool] = mapped_column(server_default=text('false'))
    joining_closed: Mapped[bool] = mapped_column(server_default=text('false'))
    created_at: Mapped[datetime] = mapped_column(server_default=text('now()'))


class Member(Base):
    """An account's membership of a trip. The table's unique key is (trip_id, account_id)."""

    __tablename__ = 'members'

    trip_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey('trips.id', ondelete='CASCADE'), primary_key=True
    )
    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey('accounts.id'), primary_key=True
    )
    role: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, server_default='active')
    joined_at: Mapped[datetime] = mapped_column(server_default=text('now()'))

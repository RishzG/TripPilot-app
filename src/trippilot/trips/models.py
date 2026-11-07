"""ORM models for the trip tables: trips and members (0001), invites, chat, concerns and plans."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    LargeBinary,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
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
    current_plan_version: Mapped[int | None] = mapped_column(Integer)
    planning_context: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True))
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


class Invite(Base):
    """A trip's invite link. Only sha256 of the raw token is stored, never the token (D-21).

    A partial unique index allows at most one row per trip with `revoked_at` null.
    """

    __tablename__ = 'invites'

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text('gen_random_uuid()')
    )
    trip_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey('trips.id', ondelete='CASCADE')
    )
    token_hash: Mapped[bytes] = mapped_column(LargeBinary, unique=True)
    created_at: Mapped[datetime] = mapped_column(server_default=text('now()'))
    revoked_at: Mapped[datetime | None]


class TravelProfile(Base):
    """One membership's preferences; budget and diet are owner-only API fields."""

    __tablename__ = 'travel_profiles'
    __table_args__ = (
        ForeignKeyConstraint(
            ['trip_id', 'account_id'], ['members.trip_id', 'members.account_id'], ondelete='CASCADE'
        ),
    )

    trip_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    account_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    origin: Mapped[str] = mapped_column(Text, server_default='')
    interests: Mapped[str] = mapped_column(Text, server_default='')
    pace: Mapped[str] = mapped_column(Text, server_default='balanced')
    budget_cents: Mapped[int | None] = mapped_column(Integer)
    dietary_notes: Mapped[str] = mapped_column(Text, server_default='')
    updated_at: Mapped[datetime] = mapped_column(server_default=text('now()'))


class TripMessage(Base):
    """An immutable public group message; the author's name is captured when sent."""

    __tablename__ = 'trip_messages'
    __table_args__ = (
        ForeignKeyConstraint(
            ['trip_id', 'account_id'], ['members.trip_id', 'members.account_id'], ondelete='CASCADE'
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    trip_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    account_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    client_message_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    author_name: Mapped[str] = mapped_column(Text)
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text('now()')
    )


class PrivateConcern(Base):
    """A member's private concern. Withdrawing erases the text but keeps the row's key.

    The tombstone stops a delayed retry of the original create from bringing the text back.
    """

    __tablename__ = 'private_concerns'
    __table_args__ = (
        ForeignKeyConstraint(
            ['trip_id', 'account_id'], ['members.trip_id', 'members.account_id'], ondelete='CASCADE'
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    trip_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    account_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    client_concern_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    content: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text('now()')
    )
    withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PlanVersion(Base):
    """One append-only draft with its original participant names and allocations."""

    __tablename__ = 'plan_versions'

    trip_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey('trips.id', ondelete='CASCADE'), primary_key=True
    )
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    request_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text('now()')
    )


class PilotRun(Base):
    """One durable request; the queue job owns execution status."""

    __tablename__ = 'pilot_runs'

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    trip_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey('trips.id', ondelete='CASCADE'), primary_key=True
    )
    job_id: Mapped[int] = mapped_column(BigInteger)
    base_version: Mapped[int] = mapped_column(Integer)
    planning_context: Mapped[dict[str, Any]] = mapped_column(JSONB)
    draft_version: Mapped[int | None] = mapped_column(Integer)
    failure: Mapped[str | None] = mapped_column(Text)


class ActivityProposal(Base):
    """One replacement revision with fixed terms and revision-specific responses."""

    __tablename__ = 'activity_proposals'

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    trip_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey('trips.id', ondelete='CASCADE')
    )
    proposal_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    revision: Mapped[int] = mapped_column(Integer)
    base_version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(Text)
    terms: Mapped[dict[str, Any]] = mapped_column(JSONB)
    accepted: Mapped[list[str]] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    applied_version: Mapped[int | None] = mapped_column(Integer)

"""ORM models for the 0004_payments tables. The schema is owned by the Alembic revision."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, ForeignKey, Identity, LargeBinary, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from trippilot.db.base import Base


class VaultToken(Base):
    """A saved PayPal payment token, stored only as Fernet ciphertext (D-05).

    At most one row per (owner_kind, owner_id) has `deleted_at` null (partial unique index).
    """

    __tablename__ = 'vault_tokens'

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text('gen_random_uuid()')
    )
    owner_kind: Mapped[str] = mapped_column(Text)
    owner_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    payer_id: Mapped[str | None] = mapped_column(Text)
    token_ciphertext: Mapped[bytes] = mapped_column(LargeBinary)
    key_version: Mapped[int]
    created_at: Mapped[datetime] = mapped_column(server_default=text('now()'))
    last_used_at: Mapped[datetime | None]
    deleted_at: Mapped[datetime | None]


class PendingVaultSetup(Base):
    """A setup token bound to the owner that created it, valid for 30 minutes (T-01-23)."""

    __tablename__ = 'pending_vault_setups'

    setup_token_id: Mapped[str] = mapped_column(Text, primary_key=True)
    owner_kind: Mapped[str] = mapped_column(Text)
    owner_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(server_default=text('now()'))
    expires_at: Mapped[datetime]


class LedgerEntry(Base):
    """One append-only audit row. `trip_id` has no foreign key on purpose."""

    __tablename__ = 'ledger_entries'

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    occurred_at: Mapped[datetime] = mapped_column(server_default=text('now()'))
    trip_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    actor_kind: Mapped[str] = mapped_column(Text)
    actor_id: Mapped[str | None] = mapped_column(Text)
    action: Mapped[str] = mapped_column(Text)
    request_id: Mapped[str | None] = mapped_column(Text)
    paypal_ids: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    amount_cents: Mapped[int | None] = mapped_column(BigInteger)
    detail: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))


class PoolBuyer(Base):
    """A simulated friend whose saved PayPal can be leased to a trip (used from 01-14)."""

    __tablename__ = 'pool_buyers'

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text('gen_random_uuid()')
    )
    slug: Mapped[str] = mapped_column(Text, unique=True)
    persona_slug: Mapped[str | None] = mapped_column(Text)
    environment: Mapped[str] = mapped_column(Text)
    sandbox_email: Mapped[str | None] = mapped_column(Text)
    vault_token_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey('vault_tokens.id')
    )
    status: Mapped[str] = mapped_column(Text, server_default='pending')
    created_at: Mapped[datetime] = mapped_column(server_default=text('now()'))


class BuyerLease(Base):
    """A pool buyer leased to a trip; a partial unique index allows one open lease per buyer."""

    __tablename__ = 'buyer_leases'

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text('gen_random_uuid()')
    )
    pool_buyer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey('pool_buyers.id')
    )
    trip_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey('trips.id', ondelete='CASCADE')
    )
    leased_at: Mapped[datetime] = mapped_column(server_default=text('now()'))
    expires_at: Mapped[datetime]
    released_at: Mapped[datetime | None]


class WebhookEvent(Base):
    """A received PayPal webhook, unique on PayPal's event id (used from 01-13)."""

    __tablename__ = 'webhook_events'

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text('gen_random_uuid()')
    )
    event_id: Mapped[str] = mapped_column(Text, unique=True)
    event_type: Mapped[str] = mapped_column(Text)
    resource_type: Mapped[str | None] = mapped_column(Text)
    resource_id: Mapped[str | None] = mapped_column(Text)
    verification_status: Mapped[str] = mapped_column(Text)
    received_at: Mapped[datetime] = mapped_column(server_default=text('now()'))
    processed_at: Mapped[datetime | None]
    summary: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))

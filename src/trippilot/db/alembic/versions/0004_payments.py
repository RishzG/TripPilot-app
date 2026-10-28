"""Payments schema: vault tokens, the append-only ledger, the buyer pool and webhook events.

One revision holds every payments table Phase 1 needs, so the later Track A plans (webhooks,
pool enrolment) add no migration. `ledger_entries` is append-only at the database: a row trigger
rejects UPDATE and DELETE and a statement trigger rejects TRUNCATE. Its `trip_id` deliberately has
no foreign key, so truncating `trips` (the test fixture does, with CASCADE) can never reach the
table whose trigger rejects TRUNCATE.

Revision ID: 0004_payments
Revises: 0003_invites_events
Create Date: 2026-10-28
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision = '0004_payments'
down_revision = '0003_invites_events'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UPGRADE_STATEMENTS = (
    # Saved PayPal (D-05): one active row per owner. The token and customer ids live only inside
    # the Fernet ciphertext; payer_id is a plain, non-secret column.
    """
    CREATE TABLE vault_tokens (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        owner_kind text NOT NULL
            CONSTRAINT vault_tokens_owner_kind_check
            CHECK (owner_kind IN ('account', 'pool_buyer')),
        owner_id uuid NOT NULL,
        payer_id text,
        token_ciphertext bytea NOT NULL,
        key_version integer NOT NULL,
        created_at timestamptz NOT NULL DEFAULT now(),
        last_used_at timestamptz,
        deleted_at timestamptz
    )
    """,
    """
    CREATE UNIQUE INDEX vault_tokens_one_active_per_owner_idx
        ON vault_tokens (owner_kind, owner_id) WHERE deleted_at IS NULL
    """,
    """
    CREATE TABLE pending_vault_setups (
        setup_token_id text PRIMARY KEY,
        owner_kind text NOT NULL
            CONSTRAINT pending_vault_setups_owner_kind_check
            CHECK (owner_kind IN ('account', 'pool_buyer')),
        owner_id uuid NOT NULL,
        created_at timestamptz NOT NULL DEFAULT now(),
        expires_at timestamptz NOT NULL
    )
    """,
    # Append-only audit ledger of every money-adjacent action (T-01-24).
    """
    CREATE TABLE ledger_entries (
        id bigserial PRIMARY KEY,
        occurred_at timestamptz NOT NULL DEFAULT now(),
        trip_id uuid,
        actor_kind text NOT NULL
            CONSTRAINT ledger_entries_actor_kind_check
            CHECK (actor_kind IN ('member', 'persona', 'system', 'script')),
        actor_id text,
        action text NOT NULL,
        request_id text,
        paypal_ids jsonb NOT NULL DEFAULT '{}'::jsonb,
        amount_cents bigint,
        detail jsonb NOT NULL DEFAULT '{}'::jsonb
    )
    """,
    'CREATE INDEX ledger_entries_trip_id_idx ON ledger_entries (trip_id) WHERE trip_id IS NOT NULL',
    'CREATE INDEX ledger_entries_request_id_idx ON ledger_entries (request_id)',
    """
    CREATE FUNCTION ledger_entries_reject_mutation() RETURNS trigger
    LANGUAGE plpgsql AS $$
    BEGIN
        RAISE EXCEPTION 'ledger_entries is append-only: % is not allowed', TG_OP
            USING ERRCODE = 'restrict_violation';
    END;
    $$
    """,
    """
    CREATE TRIGGER ledger_entries_no_update_delete
        BEFORE UPDATE OR DELETE ON ledger_entries
        FOR EACH ROW EXECUTE FUNCTION ledger_entries_reject_mutation()
    """,
    """
    CREATE TRIGGER ledger_entries_no_truncate
        BEFORE TRUNCATE ON ledger_entries
        FOR EACH STATEMENT EXECUTE FUNCTION ledger_entries_reject_mutation()
    """,
    # Simulated friends (pool buyers) and their leases (D-17: table now, no UI).
    """
    CREATE TABLE pool_buyers (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        slug text NOT NULL CONSTRAINT pool_buyers_slug_key UNIQUE,
        persona_slug text,
        environment text NOT NULL,
        sandbox_email text,
        vault_token_id uuid REFERENCES vault_tokens (id),
        status text NOT NULL DEFAULT 'pending'
            CONSTRAINT pool_buyers_status_check
            CHECK (status IN ('pending', 'enrolled', 'retired')),
        created_at timestamptz NOT NULL DEFAULT now()
    )
    """,
    """
    CREATE TABLE buyer_leases (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        pool_buyer_id uuid NOT NULL REFERENCES pool_buyers (id),
        trip_id uuid NOT NULL REFERENCES trips (id) ON DELETE CASCADE,
        leased_at timestamptz NOT NULL DEFAULT now(),
        expires_at timestamptz NOT NULL,
        released_at timestamptz
    )
    """,
    """
    CREATE UNIQUE INDEX buyer_leases_one_open_per_buyer_idx
        ON buyer_leases (pool_buyer_id) WHERE released_at IS NULL
    """,
    # Idempotent webhook inbox: PayPal's event id is unique.
    """
    CREATE TABLE webhook_events (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        event_id text NOT NULL CONSTRAINT webhook_events_event_id_key UNIQUE,
        event_type text NOT NULL,
        resource_type text,
        resource_id text,
        verification_status text NOT NULL,
        received_at timestamptz NOT NULL DEFAULT now(),
        processed_at timestamptz,
        summary jsonb NOT NULL DEFAULT '{}'::jsonb
    )
    """,
)


def upgrade() -> None:
    """Create the payments tables and the ledger's append-only triggers."""
    for statement in _UPGRADE_STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    """Drop the payments tables in reverse dependency order, then the trigger function."""
    op.execute('DROP TABLE IF EXISTS webhook_events')
    op.execute('DROP TABLE IF EXISTS buyer_leases')
    op.execute('DROP TABLE IF EXISTS pool_buyers')
    op.execute('DROP TABLE IF EXISTS ledger_entries')
    op.execute('DROP FUNCTION IF EXISTS ledger_entries_reject_mutation()')
    op.execute('DROP TABLE IF EXISTS pending_vault_setups')
    op.execute('DROP TABLE IF EXISTS vault_tokens')

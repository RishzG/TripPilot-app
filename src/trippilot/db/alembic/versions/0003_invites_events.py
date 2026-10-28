"""Invite links and the trip event log.

Adds `invites` (one active, hashed, reusable link per trip), `trip_events` (the log that the live
member list streams, one row per join, leave or removal) and the deferred foreign key from
`oauth_states.invite_id` to `invites.id` that 0001 could not declare.

Revision ID: 0003_invites_events
Revises: 0002_procrastinate
Create Date: 2026-10-28
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision = '0003_invites_events'
down_revision = '0002_procrastinate'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UPGRADE_STATEMENTS = (
    """
    CREATE TABLE invites (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        trip_id uuid NOT NULL REFERENCES trips (id) ON DELETE CASCADE,
        token_hash bytea NOT NULL CONSTRAINT invites_token_hash_key UNIQUE,
        created_at timestamptz NOT NULL DEFAULT now(),
        revoked_at timestamptz
    )
    """,
    # At most one live link per trip: a reset revokes the old row and inserts the new one in one
    # transaction, so the two can never both be live (D-21, RESEARCH Pitfall 10).
    """
    CREATE UNIQUE INDEX invites_one_active_per_trip_idx
        ON invites (trip_id) WHERE revoked_at IS NULL
    """,
    """
    CREATE TABLE trip_events (
        id bigserial PRIMARY KEY,
        trip_id uuid NOT NULL REFERENCES trips (id) ON DELETE CASCADE,
        type text NOT NULL,
        payload jsonb NOT NULL DEFAULT '{}'::jsonb,
        created_at timestamptz NOT NULL DEFAULT now()
    )
    """,
    'CREATE INDEX trip_events_trip_id_id_idx ON trip_events (trip_id, id)',
    """
    ALTER TABLE oauth_states
        ADD CONSTRAINT oauth_states_invite_id_fkey
        FOREIGN KEY (invite_id) REFERENCES invites (id) ON DELETE SET NULL
    """,
)


def upgrade() -> None:
    """Create the invite and event tables and link `oauth_states.invite_id` to `invites`."""
    for statement in _UPGRADE_STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    """Drop the foreign key and both tables in reverse dependency order."""
    op.execute('ALTER TABLE oauth_states DROP CONSTRAINT IF EXISTS oauth_states_invite_id_fkey')
    op.execute('DROP TABLE IF EXISTS trip_events')
    op.execute('DROP TABLE IF EXISTS invites')

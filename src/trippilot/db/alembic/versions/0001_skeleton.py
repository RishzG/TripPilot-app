"""Skeleton schema: accounts, sessions, oauth_states, trips and members.

Revision ID: 0001_skeleton
Revises:
Create Date: 2026-10-28
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision = '0001_skeleton'
down_revision = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UPGRADE_STATEMENTS = (
    """
    CREATE TABLE accounts (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        kind text NOT NULL DEFAULT 'member'
            CONSTRAINT accounts_kind_check CHECK (kind IN ('member', 'persona')),
        paypal_subject text UNIQUE,
        persona_slug text UNIQUE,
        email text,
        display_name text NOT NULL,
        nickname text,
        avatar_kind text NOT NULL DEFAULT 'initials'
            CONSTRAINT accounts_avatar_kind_check
            CHECK (avatar_kind IN ('initials', 'illustrated')),
        avatar_key text,
        created_at timestamptz NOT NULL DEFAULT now()
    )
    """,
    """
    CREATE TABLE sessions (
        id_hash bytea PRIMARY KEY,
        account_id uuid NOT NULL REFERENCES accounts (id) ON DELETE CASCADE,
        created_at timestamptz NOT NULL DEFAULT now(),
        last_seen_at timestamptz NOT NULL DEFAULT now(),
        expires_at timestamptz NOT NULL,
        user_agent text,
        is_persona boolean NOT NULL DEFAULT false
    )
    """,
    'CREATE INDEX sessions_account_id_idx ON sessions (account_id)',
    """
    CREATE TABLE oauth_states (
        state_hash bytea PRIMARY KEY,
        invite_id uuid,
        next_path text,
        created_at timestamptz NOT NULL DEFAULT now(),
        expires_at timestamptz NOT NULL,
        consumed_at timestamptz
    )
    """,
    """
    CREATE TABLE trips (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        name text NOT NULL
            CONSTRAINT trips_name_length_check CHECK (char_length(name) BETWEEN 1 AND 80),
        organiser_account_id uuid NOT NULL REFERENCES accounts (id),
        demo_mode boolean NOT NULL DEFAULT false,
        joining_closed boolean NOT NULL DEFAULT false,
        created_at timestamptz NOT NULL DEFAULT now()
    )
    """,
    """
    CREATE TABLE members (
        trip_id uuid NOT NULL REFERENCES trips (id) ON DELETE CASCADE,
        account_id uuid NOT NULL REFERENCES accounts (id),
        role text NOT NULL
            CONSTRAINT members_role_check CHECK (role IN ('organiser', 'member')),
        status text NOT NULL DEFAULT 'active'
            CONSTRAINT members_status_check CHECK (status IN ('active', 'left', 'removed')),
        joined_at timestamptz NOT NULL DEFAULT now(),
        CONSTRAINT members_trip_account_key UNIQUE (trip_id, account_id)
    )
    """,
    'CREATE INDEX members_account_id_idx ON members (account_id)',
)


def upgrade() -> None:
    """Create the skeleton tables (D-03 session tables, D-20 trips with organiser and name)."""
    for statement in _UPGRADE_STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    """Drop the skeleton tables in reverse dependency order."""
    for table in ('members', 'trips', 'oauth_states', 'sessions', 'accounts'):
        op.execute(f'DROP TABLE IF EXISTS {table}')

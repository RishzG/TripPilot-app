"""Persist group chat with membership ownership and retry-safe client message IDs."""

from collections.abc import Sequence

from alembic import op

revision = '0006_trip_messages'
down_revision = '0005_travel_profiles'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add ordered history; each sender's client message ID is unique within the trip."""
    op.execute("""
        CREATE TABLE trip_messages (
            id bigserial PRIMARY KEY,
            trip_id uuid NOT NULL,
            account_id uuid NOT NULL,
            client_message_id uuid NOT NULL,
            author_name text NOT NULL,
            content text NOT NULL CHECK (char_length(content) BETWEEN 1 AND 4000),
            created_at timestamptz NOT NULL DEFAULT now(),
            FOREIGN KEY (trip_id, account_id)
                REFERENCES members (trip_id, account_id) ON DELETE CASCADE,
            UNIQUE (trip_id, account_id, client_message_id)
        )
    """)
    op.execute('CREATE INDEX trip_messages_history_idx ON trip_messages (trip_id, id DESC)')


def downgrade() -> None:
    """Remove group chat without changing trip membership."""
    op.execute('DROP TABLE trip_messages')

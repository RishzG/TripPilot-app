"""Add private concerns (author-owned, anonymous to the leader)."""

from collections.abc import Sequence

from alembic import op

revision = '0007_private_concerns'
down_revision = '0006_trip_messages'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create private concerns; a withdrawn concern keeps its key but loses its text."""
    op.execute("""
        CREATE TABLE private_concerns (
            id bigserial PRIMARY KEY,
            trip_id uuid NOT NULL,
            account_id uuid NOT NULL,
            client_concern_id uuid NOT NULL,
            content text,
            created_at timestamptz NOT NULL DEFAULT now(),
            withdrawn_at timestamptz,
            FOREIGN KEY (trip_id, account_id)
                REFERENCES members (trip_id, account_id) ON DELETE CASCADE,
            UNIQUE (trip_id, account_id, client_concern_id),
            CHECK (
                (withdrawn_at IS NULL AND content IS NOT NULL
                    AND char_length(content) BETWEEN 1 AND 1000)
                OR (withdrawn_at IS NOT NULL AND content IS NULL)
            )
        )
    """)
    op.execute("""
        CREATE INDEX private_concerns_open_idx ON private_concerns (trip_id, created_at, id)
            WHERE withdrawn_at IS NULL
    """)


def downgrade() -> None:
    """Remove private concerns without changing trip membership."""
    op.execute('DROP TABLE private_concerns')

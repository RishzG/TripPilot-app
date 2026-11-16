"""Add immutable itinerary snapshots."""

from collections.abc import Sequence

from alembic import op

revision = '0008_plan_versions'
down_revision = '0007_private_concerns'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE plan_versions (
            trip_id uuid NOT NULL REFERENCES trips(id) ON DELETE CASCADE,
            version integer NOT NULL CHECK (version > 0),
            request_id uuid NOT NULL,
            snapshot jsonb NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (trip_id, version),
            UNIQUE (trip_id, request_id)
        )
    """)


def downgrade() -> None:
    op.execute('DROP TABLE plan_versions')

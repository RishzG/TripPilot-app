"""Trip-scoped travel profiles with private budget and dietary preferences.

Revision ID: 0005_travel_profiles
Revises: 0004_payments
"""

from collections.abc import Sequence

from alembic import op

revision = '0005_travel_profiles'
down_revision = '0004_payments'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Keep preferences separate from identity and scoped to a trip membership."""
    op.execute("""
        CREATE TABLE travel_profiles (
            trip_id uuid NOT NULL,
            account_id uuid NOT NULL,
            origin text NOT NULL DEFAULT '',
            interests text NOT NULL DEFAULT '',
            pace text NOT NULL DEFAULT 'balanced'
                CHECK (pace IN ('relaxed', 'balanced', 'active')),
            budget_cents integer CHECK (budget_cents BETWEEN 0 AND 100000000),
            dietary_notes text NOT NULL DEFAULT '',
            updated_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (trip_id, account_id),
            FOREIGN KEY (trip_id, account_id)
                REFERENCES members (trip_id, account_id) ON DELETE CASCADE
        )
    """)


def downgrade() -> None:
    """Remove travel preferences without changing accounts or memberships."""
    op.execute('DROP TABLE travel_profiles')

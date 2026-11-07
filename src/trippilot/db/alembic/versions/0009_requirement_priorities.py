"""Explicit private requirement priorities."""

from alembic import op

revision = '0009_requirement_priorities'
down_revision = '0008_planning'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Preserve existing profiles with empty explicit requirements."""
    op.execute(
        """ALTER TABLE travel_profiles ADD COLUMN must_haves text NOT NULL DEFAULT '',
        ADD COLUMN preferred text NOT NULL DEFAULT ''"""
    )


def downgrade() -> None:
    """Remove explicit priority fields."""
    op.execute('ALTER TABLE travel_profiles DROP COLUMN preferred, DROP COLUMN must_haves')

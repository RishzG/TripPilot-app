"""Apply the procrastinate job-queue schema exactly once.

The schema SQL ships with the pinned procrastinate release and is executed here, inside the
Alembic chain, so it is applied once per database. Never run `procrastinate schema --apply`
at deploy time (RESEARCH Pitfall 9). When procrastinate is upgraded, add a new Alembic revision
that runs the matching files from `SchemaManager.get_migrations_path()`; do not edit this one.

Revision ID: 0002_procrastinate
Revises: 0001_skeleton
Create Date: 2026-10-28
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
from procrastinate.schema import SchemaManager

revision = '0002_procrastinate'
down_revision = '0001_skeleton'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DROP_PROCRASTINATE_OBJECTS = r"""
DO $$
DECLARE
    obj record;
BEGIN
    FOR obj IN
        SELECT tablename AS name FROM pg_tables
        WHERE schemaname = current_schema() AND tablename LIKE 'procrastinate\_%'
    LOOP
        EXECUTE format('DROP TABLE IF EXISTS %I CASCADE', obj.name);
    END LOOP;
    FOR obj IN
        SELECT p.oid::regprocedure::text AS name FROM pg_proc p
        JOIN pg_namespace n ON n.oid = p.pronamespace
        WHERE n.nspname = current_schema() AND p.proname LIKE 'procrastinate\_%'
    LOOP
        EXECUTE format('DROP FUNCTION IF EXISTS %s CASCADE', obj.name);
    END LOOP;
    FOR obj IN
        SELECT t.typname AS name FROM pg_type t
        JOIN pg_namespace n ON n.oid = t.typnamespace
        WHERE n.nspname = current_schema() AND t.typname LIKE 'procrastinate\_%'
          AND t.typtype IN ('e', 'c')
    LOOP
        EXECUTE format('DROP TYPE IF EXISTS %I CASCADE', obj.name);
    END LOOP;
END
$$
"""


def upgrade() -> None:
    """Execute the procrastinate schema SQL once.

    Percent signs are doubled exactly as `SchemaManager.apply_schema` does, because the driver
    treats the statement as a parameterised query.
    """
    schema = SchemaManager.get_schema().replace('%', '%%')
    op.get_bind().exec_driver_sql(schema)


def downgrade() -> None:
    """Drop every procrastinate table, function and type."""
    op.get_bind().exec_driver_sql(_DROP_PROCRASTINATE_OBJECTS.replace('%', '%%'))

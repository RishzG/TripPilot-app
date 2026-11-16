"""Add trip planning context and durable Pilot draft requests."""

from alembic import op

revision = '0009_pilot_drafts'
down_revision = '0008_plan_versions'


def upgrade() -> None:
    op.execute('ALTER TABLE trips ADD COLUMN planning_context jsonb')
    op.execute("""
        CREATE TABLE pilot_runs (
            id uuid NOT NULL,
            trip_id uuid NOT NULL REFERENCES trips(id) ON DELETE CASCADE,
            job_id bigint NOT NULL,
            base_version integer NOT NULL,
            planning_context jsonb NOT NULL,
            draft_version integer,
            failure text,
            PRIMARY KEY (trip_id, id),
            UNIQUE (trip_id, job_id)
        )
    """)


def downgrade() -> None:
    op.execute('DROP TABLE pilot_runs')
    op.execute('ALTER TABLE trips DROP COLUMN planning_context')

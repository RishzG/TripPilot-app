"""Select current plans and preserve individual replacement revisions."""

from alembic import op

revision = '0010_activity_replanning'
down_revision = '0009_pilot_drafts'


def upgrade() -> None:
    op.execute('ALTER TABLE trips ADD COLUMN current_plan_version integer')
    op.execute("""
        ALTER TABLE trips ADD CONSTRAINT trips_current_plan_fk
        FOREIGN KEY (id, current_plan_version) REFERENCES plan_versions (trip_id, version)
        DEFERRABLE INITIALLY DEFERRED
    """)
    op.execute("""
        CREATE TABLE activity_proposals (
            id bigserial PRIMARY KEY,
            trip_id uuid NOT NULL REFERENCES trips(id) ON DELETE CASCADE,
            proposal_id uuid NOT NULL,
            revision integer NOT NULL CHECK (revision > 0),
            base_version integer NOT NULL CHECK (base_version > 0),
            status text NOT NULL CHECK (status IN ('open', 'superseded', 'applied', 'withdrawn')),
            terms jsonb NOT NULL,
            accepted jsonb NOT NULL DEFAULT '[]'::jsonb,
            applied_version integer,
            UNIQUE (trip_id, proposal_id, revision)
        )
    """)
    op.execute("""
        CREATE UNIQUE INDEX activity_proposals_one_open ON activity_proposals (trip_id)
        WHERE status = 'open'
    """)
    op.execute('CREATE INDEX activity_proposals_trip_history ON activity_proposals (trip_id, id)')


def downgrade() -> None:
    op.execute('DROP TABLE activity_proposals')
    op.execute('ALTER TABLE trips DROP COLUMN current_plan_version')

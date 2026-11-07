"""Shared scheduling context, immutable plans, durable Pilot runs and decisions."""

from alembic import op

revision = '0008_planning'
down_revision = '0007_private_concerns'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Install the planning domain without changing existing trip membership."""
    op.execute("""
        ALTER TABLE trips ADD COLUMN destination text NOT NULL DEFAULT '',
            ADD COLUMN start_date date, ADD COLUMN end_date date,
            ADD COLUMN timezone text NOT NULL DEFAULT 'UTC',
            ADD COLUMN context_revision integer NOT NULL DEFAULT 0,
            ADD COLUMN selected_plan_id uuid,
            ADD CHECK ((start_date IS NULL AND end_date IS NULL) OR
                (start_date IS NOT NULL AND end_date IS NOT NULL AND end_date >= start_date));
        CREATE TABLE plan_versions (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            trip_id uuid NOT NULL REFERENCES trips(id) ON DELETE CASCADE,
            title text NOT NULL, sample boolean NOT NULL DEFAULT false,
            context_revision integer NOT NULL, input_fingerprint text NOT NULL,
            items jsonb NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX plan_versions_trip_idx ON plan_versions(trip_id, created_at);
        CREATE TABLE plan_private_notes (
            plan_id uuid NOT NULL REFERENCES plan_versions(id) ON DELETE CASCADE,
            account_id uuid NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
            rationale text NOT NULL, PRIMARY KEY(plan_id, account_id)
        );
        CREATE FUNCTION immutable_plan() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN RAISE EXCEPTION 'Plan versions are immutable'; END $$;
        CREATE TRIGGER plan_versions_immutable BEFORE UPDATE ON plan_versions
            FOR EACH ROW EXECUTE FUNCTION immutable_plan();
        CREATE TABLE pilot_runs (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            trip_id uuid NOT NULL REFERENCES trips(id) ON DELETE CASCADE,
            client_id uuid NOT NULL, context_revision integer NOT NULL,
            status text NOT NULL DEFAULT 'queued' CHECK
                (status IN ('queued','running','failed','completed')),
            attempts integer NOT NULL DEFAULT 0, lease_until timestamptz,
            plan_id uuid REFERENCES plan_versions(id) ON DELETE CASCADE,
            error text, usage jsonb NOT NULL DEFAULT '{}',
            base_id uuid REFERENCES plan_versions(id) ON DELETE CASCADE,
            cancelled_item_id uuid,
            created_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE(trip_id, client_id)
        );
        CREATE UNIQUE INDEX pilot_one_active ON pilot_runs(trip_id)
            WHERE status IN ('queued','running');
        CREATE TABLE plan_proposals (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            trip_id uuid NOT NULL REFERENCES trips(id) ON DELETE CASCADE,
            base_id uuid NOT NULL REFERENCES plan_versions(id) ON DELETE CASCADE,
            version_id uuid NOT NULL REFERENCES plan_versions(id) ON DELETE CASCADE,
            cancelled_item_id uuid NOT NULL, affected jsonb NOT NULL,
            responses jsonb NOT NULL DEFAULT '{}',
            status text NOT NULL DEFAULT 'open' CHECK(status IN ('open','accepted')),
            created_at timestamptz NOT NULL DEFAULT now()
        );
    """)


def downgrade() -> None:
    """Remove planning data and context."""
    op.execute("""
        DROP TABLE plan_proposals; DROP TABLE pilot_runs; DROP TABLE plan_private_notes;
        DROP TABLE plan_versions;
        DROP FUNCTION immutable_plan();
        ALTER TABLE trips DROP COLUMN selected_plan_id, DROP COLUMN context_revision,
            DROP COLUMN timezone, DROP COLUMN end_date, DROP COLUMN start_date,
            DROP COLUMN destination;
    """)

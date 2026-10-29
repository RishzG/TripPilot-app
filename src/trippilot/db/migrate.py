"""Advisory-locked `alembic upgrade head`, run once per deploy (01-07, T-01-21).

Render runs this as the web service's pre-deploy command (`python -m trippilot.db.migrate`), and
the same command is the fallback in the start command if a platform ignores pre-deploy for image
services (RESEARCH A12). Two callers can overlap (a pre-deploy plus a start-time fallback, or a
redeploy during a rollout), so the upgrade runs while one dedicated connection holds a Postgres
advisory lock: the second caller waits for the first to finish and then upgrades nothing.

The lock is session-scoped, so it is also released if this process dies mid-migration.
"""

from __future__ import annotations

import sys
from pathlib import Path

import psycopg
from alembic import command
from alembic.config import Config
from sqlalchemy.engine import make_url

from trippilot.settings import get_settings

MIGRATION_LOCK_KEY = 727001
"""The fixed advisory-lock key every migration run contends on."""

ALEMBIC_INI = Path(__file__).resolve().parents[3] / 'alembic.ini'


def _lock_dsn() -> str:
    """Return the configured database URL in the form `psycopg.connect` accepts."""
    url = make_url(get_settings().database_url).set(drivername='postgresql')
    return url.render_as_string(hide_password=False)


def run_migrations() -> None:
    """Upgrade the database to the Alembic head while holding the migration advisory lock.

    The lock lives on its own autocommit connection that stays open for the whole upgrade; the
    upgrade itself opens its own connection (see `alembic/env.py`). Blocks while another run
    holds the lock. This is synchronous because `env.py` drives its own event loop.
    """
    with psycopg.connect(_lock_dsn(), autocommit=True) as lock_connection:
        lock_connection.execute('SELECT pg_advisory_lock(%s)', (MIGRATION_LOCK_KEY,))
        try:
            command.upgrade(Config(str(ALEMBIC_INI)), 'head')
        finally:
            lock_connection.execute('SELECT pg_advisory_unlock(%s)', (MIGRATION_LOCK_KEY,))


def main() -> int:
    """Entry point for `python -m trippilot.db.migrate`."""
    run_migrations()
    print('migrations: database is at the Alembic head')
    return 0


if __name__ == '__main__':
    sys.exit(main())

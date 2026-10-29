"""Advisory-locked `alembic upgrade head`, run once per deploy (01-07, T-01-21).

Render runs this as the web service's pre-deploy command (`python -m trippilot.db.migrate`), and
the same command is the fallback in the start command if a platform ignores pre-deploy for image
services (RESEARCH A12). Two callers can overlap (a pre-deploy plus a start-time fallback, or a
redeploy during a rollout), so the upgrade runs while one dedicated connection holds a Postgres
advisory lock: the second caller waits for the first to finish and then upgrades nothing.

The lock is session-scoped, so it is also released if this process dies mid-migration.

A freshly created Render Postgres can refuse connections for a short while after Render reports it
created (the first staging deploy failed exactly so), so the lock connection retries for a bounded
time before giving up.
"""

from __future__ import annotations

import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import psycopg
from alembic import command
from alembic.config import Config
from sqlalchemy.engine import make_url

from trippilot.settings import get_settings

MIGRATION_LOCK_KEY = 727001
"""The fixed advisory-lock key every migration run contends on."""

ALEMBIC_INI = Path(__file__).resolve().parents[3] / 'alembic.ini'

CONNECT_TIMEOUT_SECONDS = 60.0
"""How long to keep retrying a database that refuses connections before failing the deploy."""

CONNECT_RETRY_SECONDS = 2.0
"""The wait between connection attempts."""


def _lock_dsn() -> str:
    """Return the configured database URL in the form `psycopg.connect` accepts."""
    url = make_url(get_settings().database_url).set(drivername='postgresql')
    return url.render_as_string(hide_password=False)


def connect_for_lock(
    dsn: str,
    *,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
) -> psycopg.Connection[Any]:
    """Open the autocommit lock connection, retrying while the database is not yet accepting.

    Raises the last `psycopg.OperationalError` once `CONNECT_TIMEOUT_SECONDS` have passed.
    """
    deadline = monotonic() + CONNECT_TIMEOUT_SECONDS
    while True:
        try:
            return psycopg.connect(dsn, autocommit=True)
        except psycopg.OperationalError:
            if monotonic() >= deadline:
                raise
            print('migrations: database not accepting connections yet; retrying', file=sys.stderr)
            sleep(CONNECT_RETRY_SECONDS)


def run_migrations() -> None:
    """Upgrade the database to the Alembic head while holding the migration advisory lock.

    The lock lives on its own autocommit connection that stays open for the whole upgrade; the
    upgrade itself opens its own connection (see `alembic/env.py`). Blocks while another run
    holds the lock. This is synchronous because `env.py` drives its own event loop.
    """
    with connect_for_lock(_lock_dsn()) as lock_connection:
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

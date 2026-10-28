"""The procrastinate application: one connector, the task modules the worker must import.

The worker process starts with `procrastinate --app=trippilot.jobs.app.app worker`. The schema
is applied once by Alembic revision 0002 and never by the procrastinate CLI (RESEARCH Pitfall 9).
"""

from __future__ import annotations

import procrastinate

from trippilot.settings import get_settings

_DRIVER_SUFFIX = '+psycopg'

JOB_POOL_MAX_SIZE = 4
"""Connections the procrastinate pool may hold per process (Render allows 100 in total)."""


def libpq_conninfo(database_url: str) -> str:
    """Return the URL with the SQLAlchemy `+psycopg` driver suffix removed for libpq."""
    return database_url.replace(_DRIVER_SUFFIX, '', 1)


app = procrastinate.App(
    connector=procrastinate.PsycopgConnector(
        conninfo=libpq_conninfo(get_settings().database_url),
        min_size=1,
        max_size=JOB_POOL_MAX_SIZE,
    ),
    import_paths=['trippilot.jobs.tasks', 'trippilot.payments.tasks'],
)

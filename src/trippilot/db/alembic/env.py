"""Alembic environment: async online migrations on the application's psycopg 3 URL.

Migrations are hand-written, so there is no model metadata (`target_metadata = None`) and no
autogenerate. Offline (SQL script) mode is not supported.
"""

from __future__ import annotations

import asyncio
from typing import Any

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from trippilot.db.engine import configure_event_loop_policy
from trippilot.settings import get_settings

target_metadata = None


def _run_migrations(connection: Connection) -> None:
    """Configure the Alembic context on a synchronous connection and run the migrations."""
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def _run_async_migrations() -> None:
    """Open a throwaway async engine (no pooling) and run the migrations through it."""
    engine = create_async_engine(get_settings().database_url, poolclass=pool.NullPool)
    async with engine.connect() as connection:
        await connection.run_sync(_run_migrations)
    await engine.dispose()


def run_migrations_online() -> None:
    """Run migrations against the configured database."""
    configure_event_loop_policy()
    asyncio.run(_run_async_migrations())


def _unsupported_offline(*_args: Any, **_kwargs: Any) -> None:
    """Fail loudly: migrations need a live database (the procrastinate schema is applied once)."""
    raise RuntimeError('Offline migrations are not supported; run against a database.')


if context.is_offline_mode():
    _unsupported_offline()
else:
    run_migrations_online()

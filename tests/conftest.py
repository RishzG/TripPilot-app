"""Shared pytest fixtures: Selector event loop, throwaway test database, client and session."""

from __future__ import annotations

import asyncio
import os
import sys
from collections.abc import AsyncIterator, Callable, Iterator

import httpx
import psycopg
import pytest
from psycopg import sql
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession

# psycopg async is incompatible with the Windows Proactor loop (RESEARCH R5): this must run
# before any event loop is created.
if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

DEFAULT_TEST_DATABASE_URL = 'postgresql+psycopg://postgres:postgres@localhost:5432/trippilot_test'


def derive_test_database_url() -> str:
    """Return the test database URL derived from DATABASE_URL.

    The database name always ends in `_test`, so the suite can never touch a development or
    production database even when DATABASE_URL points at one.
    """
    raw = os.environ.get('DATABASE_URL')
    if not raw:
        return DEFAULT_TEST_DATABASE_URL
    url = make_url(raw.replace('postgresql://', 'postgresql+psycopg://', 1))
    url = url.set(drivername='postgresql+psycopg')
    name = url.database or 'trippilot'
    if not name.endswith('_test'):
        url = url.set(database=f'{name}_test')
    return url.render_as_string(hide_password=False)


TEST_DATABASE_URL = derive_test_database_url()
# Point Settings (and therefore the engine and Alembic) at the test database for the whole
# session. Environment variables outrank any local .env file.
os.environ['DATABASE_URL'] = TEST_DATABASE_URL


def _maintenance_connection() -> psycopg.Connection[tuple[object, ...]]:
    """Open an autocommit psycopg connection to the `postgres` maintenance database."""
    url = make_url(TEST_DATABASE_URL)
    return psycopg.connect(
        host=url.host,
        port=url.port,
        user=url.username,
        password=url.password,
        dbname='postgres',
        autocommit=True,
    )


def ensure_test_database() -> None:
    """Create the test database if it does not exist yet."""
    name = make_url(TEST_DATABASE_URL).database
    assert name is not None
    with _maintenance_connection() as conn:
        exists = conn.execute('SELECT 1 FROM pg_database WHERE datname = %s', (name,)).fetchone()
        if exists is None:
            conn.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))


Conn = psycopg.Connection[tuple[object, ...]]

TRUNCATION_EXCLUDED_TABLES = frozenset({'alembic_version', 'ledger_entries'})
"""Tables never truncated between tests.

`alembic_version` is migration bookkeeping; `ledger_entries` is append-only (a BEFORE TRUNCATE
trigger from revision 0004 raises) and its trip_id has no foreign key, so CASCADE never reaches it.
"""


def application_tables(conn: Conn) -> list[str]:
    """Return every public table that tests may truncate, read live from `pg_tables`.

    Reading the list from the catalog means tables added by later revisions (invites, trip
    events, vault tokens, webhook events, magic links, ...) are included without editing this
    module.
    """
    rows = conn.execute(
        "SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename"
    ).fetchall()
    return [str(row[0]) for row in rows if row[0] not in TRUNCATION_EXCLUDED_TABLES]


def truncate_application_tables(conn: Conn, tables: list[str]) -> None:
    """Truncate the given tables in one `TRUNCATE ... RESTART IDENTITY CASCADE` statement."""
    if not tables:
        return
    names = sql.SQL(', ').join(sql.Identifier('public', name) for name in tables)
    conn.execute(sql.SQL('TRUNCATE {} RESTART IDENTITY CASCADE').format(names))


@pytest.fixture
def table_helpers() -> tuple[Callable[[Conn], list[str]], Callable[[Conn, list[str]], None]]:
    """Return (application_tables, truncate_application_tables) for tests of the isolation rule."""
    return application_tables, truncate_application_tables


@pytest.fixture
def sync_conn(test_database: str) -> Iterator[Conn]:
    """Yield an autocommit psycopg connection to the test database for catalog checks."""
    url = make_url(test_database)
    with psycopg.connect(
        host=url.host,
        port=url.port,
        user=url.username,
        password=url.password,
        dbname=url.database,
        autocommit=True,
    ) as conn:
        yield conn


@pytest.fixture(scope='session', autouse=True)
def test_database() -> str:
    """Make sure the test database exists and return its URL."""
    from trippilot.settings import get_settings

    ensure_test_database()
    get_settings.cache_clear()
    return TEST_DATABASE_URL


@pytest.fixture
async def db(test_database: str) -> AsyncIterator[AsyncSession]:
    """Yield an AsyncSession on the test database; the engine is rebuilt per test."""
    from trippilot.db.engine import dispose_engine, get_engine, session_factory

    get_engine()
    async with session_factory() as session:
        yield session
    await dispose_engine()


@pytest.fixture
async def client(test_database: str) -> AsyncIterator[httpx.AsyncClient]:
    """Yield an httpx client speaking ASGI to a fresh `create_app()` instance."""
    from trippilot.app import create_app
    from trippilot.db.engine import dispose_engine

    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url='http://test') as http_client:
        yield http_client
    await dispose_engine()

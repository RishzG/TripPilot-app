"""Shared pytest fixtures: Selector event loop, throwaway test database, client and session."""

from __future__ import annotations

import asyncio
import os
import sys
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from pathlib import Path
from typing import TYPE_CHECKING

import httpx
import psycopg
import pytest
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from psycopg import sql
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession

if TYPE_CHECKING:
    from trippilot.auth.models import Account

# psycopg async is incompatible with the Windows Proactor loop (RESEARCH R5): this must run
# before any event loop is created.
if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

REPO_ROOT = Path(__file__).resolve().parent.parent

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


def recreate_test_database() -> None:
    """Drop and recreate the test database so every session starts from nothing."""
    name = make_url(TEST_DATABASE_URL).database
    assert name is not None
    with _maintenance_connection() as conn:
        quoted = sql.Identifier(name)
        conn.execute(sql.SQL('DROP DATABASE IF EXISTS {} WITH (FORCE)').format(quoted))
        conn.execute(sql.SQL('CREATE DATABASE {}').format(quoted))


def upgrade_test_database() -> None:
    """Run `alembic upgrade head` once against the test database (URL comes from Settings)."""
    config = Config(str(REPO_ROOT / 'alembic.ini'))
    command.upgrade(config, 'head')


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
    with _maintenance_connection_to_test_database() as conn:
        yield conn


_truncatable_tables: list[str] = []
"""Names read from `pg_tables` once per session, right after the upgrade."""

_DATABASE_FIXTURES = frozenset({'db', 'client', 'sync_conn', 'test_database'})


@pytest.fixture(scope='session')
def test_database() -> str:
    """Create a fresh test database, migrate it to head once, and return its URL.

    The fixture is lazy: unit tests that never touch the database do not need Postgres.
    """
    from trippilot.settings import get_settings

    recreate_test_database()
    get_settings.cache_clear()
    upgrade_test_database()
    get_settings.cache_clear()
    with _maintenance_connection_to_test_database() as conn:
        _truncatable_tables[:] = application_tables(conn)
    return TEST_DATABASE_URL


def _maintenance_connection_to_test_database() -> Conn:
    """Open an autocommit psycopg connection to the test database itself."""
    url = make_url(TEST_DATABASE_URL)
    return psycopg.connect(
        host=url.host,
        port=url.port,
        user=url.username,
        password=url.password,
        dbname=url.database,
        autocommit=True,
    )


@pytest.fixture(autouse=True)
def _empty_application_tables(request: pytest.FixtureRequest) -> None:
    """Start every database-backed test with every application table empty.

    The tables truncated are every public table except `alembic_version` and `ledger_entries`,
    discovered from `pg_tables` after the upgrade, so tables added by later revisions are cleared
    without editing this fixture. Tests under `tests/integration`, and any test that requests
    `db`, `client` or `sync_conn`, get a truncation before they run.

    RULE FOR EVERY LATER TEST: `ledger_entries` is append-only (a BEFORE TRUNCATE trigger from
    revision 0004 raises) and its rows persist across tests. Assertions on it must filter by a
    trip_id, request_id or actor_id that is unique to the test and must never count all rows or
    assume ids start at 1.
    """
    in_integration = 'integration' in request.path.parts
    if not in_integration and _DATABASE_FIXTURES.isdisjoint(request.fixturenames):
        return
    request.getfixturevalue('test_database')
    with _maintenance_connection_to_test_database() as conn:
        truncate_application_tables(conn, _truncatable_tables)


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


MakeApp = Callable[[bool], FastAPI]
MakeClient = Callable[[FastAPI], httpx.AsyncClient]
MakeMember = Callable[..., Awaitable[tuple['Account', str]]]


@pytest.fixture
def make_app() -> MakeApp:
    """Return a factory building an app whose `demo_mode` is set explicitly.

    Tests never rely on the ambient `DEMO_MODE` (a local `.env` may set it): the settings object
    is a copy with the flag forced, which is also how D-15 is exercised in both directions.
    """
    from trippilot.app import create_app
    from trippilot.settings import get_settings

    def _make(demo_mode: bool) -> FastAPI:
        settings = get_settings().model_copy(update={'demo_mode': demo_mode})
        return create_app(settings)

    return _make


@pytest.fixture
async def make_client(test_database: str) -> AsyncIterator[MakeClient]:
    """Return a factory for httpx clients bound to an app, each with its own cookie jar.

    Every client is closed and the engine disposed at teardown.
    """
    from trippilot.db.engine import dispose_engine

    clients: list[httpx.AsyncClient] = []

    def _make(app: FastAPI) -> httpx.AsyncClient:
        http_client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url='http://test'
        )
        clients.append(http_client)
        return http_client

    yield _make
    for http_client in clients:
        await http_client.aclose()
    await dispose_engine()


@pytest.fixture
async def make_member(test_database: str) -> AsyncIterator[MakeMember]:
    """Return `make_member(display_name='Test Member') -> (Account, raw_cookie_value)`.

    Inserts a member account and calls `create_session` directly (no HTTP), committing so the
    app under test can see both rows.
    """
    from trippilot.auth.models import Account
    from trippilot.auth.sessions import create_session
    from trippilot.db.engine import dispose_engine, get_engine, session_factory

    async def _make(display_name: str = 'Test Member') -> tuple[Account, str]:
        get_engine()
        async with session_factory() as session:
            account = Account(kind='member', display_name=display_name)
            session.add(account)
            await session.flush()
            raw = await create_session(session, account.id, is_persona=False, user_agent='pytest')
            await session.commit()
        return account, raw

    yield _make
    await dispose_engine()

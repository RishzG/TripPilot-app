"""Integration tests for GET /api/health: the tracer path from request to Postgres."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import httpx
import psycopg
from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from trippilot.app import create_app
from trippilot.db.engine import get_db
from trippilot.settings import get_settings

REPO_ROOT = Path(__file__).resolve().parents[2]


def _single_migration_head() -> str:
    """Return the one Alembic head on disk, failing if the chain has branched."""
    heads = ScriptDirectory.from_config(Config(str(REPO_ROOT / 'alembic.ini'))).get_heads()
    assert len(heads) == 1
    return heads[0]


async def test_health_reaches_postgres(client: httpx.AsyncClient) -> None:
    """GET /api/health answers 200 with db 'ok' after a real SELECT 1."""
    response = await client.get('/api/health')

    assert response.status_code == 200
    assert response.json() == {
        'status': 'ok',
        'git_sha': get_settings().app_git_sha,
        'db': 'ok',
        'worker_last_seen_seconds': None,
    }


async def test_health_reports_db_error_without_leaking_details() -> None:
    """When the session raises OperationalError the body says 'error' and nothing more."""
    app: FastAPI = create_app()

    class _BrokenSession:
        """Session stand-in whose execute always fails like an unreachable database."""

        async def execute(self, *_args: object, **_kwargs: object) -> None:
            raise OperationalError('SELECT 1', {}, Exception('password=hunter2 host=secret-db'))

    async def broken_db() -> object:
        return _BrokenSession()

    app.dependency_overrides[get_db] = broken_db
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url='http://test') as http_client:
        response = await http_client.get('/api/health')

    assert response.status_code == 200
    assert response.json() == {
        'status': 'ok',
        'git_sha': get_settings().app_git_sha,
        'db': 'error',
        'worker_last_seen_seconds': None,
    }
    assert 'hunter2' not in response.text
    assert 'secret-db' not in response.text
    assert 'SELECT' not in response.text


async def test_health_response_carries_security_headers(client: httpx.AsyncClient) -> None:
    """Every response carries the hardening headers and a report-only CSP."""
    response = await client.get('/api/health')

    assert response.headers['referrer-policy'] == 'no-referrer'
    assert response.headers['x-frame-options'] == 'DENY'
    assert response.headers['x-content-type-options'] == 'nosniff'
    csp = response.headers['content-security-policy-report-only']
    assert 'https://www.sandbox.paypal.com' in csp
    assert 'https://www.paypalobjects.com' in csp
    assert 'https://api-m.sandbox.paypal.com' in csp
    assert 'content-security-policy' not in response.headers


# ---- Alembic baseline and per-test isolation (Task 2) ----

Conn = psycopg.Connection[tuple[object, ...]]
TableHelpers = tuple[Callable[[Conn], list[str]], Callable[[Conn, list[str]], None]]

EXPECTED_COLUMNS: dict[str, set[str]] = {
    'accounts': {
        'id',
        'kind',
        'paypal_subject',
        'persona_slug',
        'email',
        'display_name',
        'nickname',
        'avatar_kind',
        'avatar_key',
        'created_at',
    },
    'sessions': {
        'id_hash',
        'account_id',
        'created_at',
        'last_seen_at',
        'expires_at',
        'user_agent',
        'is_persona',
    },
    'oauth_states': {
        'state_hash',
        'invite_id',
        'next_path',
        'created_at',
        'expires_at',
        'consumed_at',
    },
    'trips': {
        'id',
        'name',
        'organiser_account_id',
        'demo_mode',
        'joining_closed',
        'created_at',
    },
    'members': {'trip_id', 'account_id', 'role', 'status', 'joined_at'},
}


async def _regclass(db: AsyncSession, name: str) -> object:
    """Return `to_regclass(name)`, which is None when the relation does not exist."""
    result = await db.execute(text('SELECT to_regclass(:name)'), {'name': name})
    return result.scalar_one()


async def test_database_is_migrated_to_the_single_head(db: AsyncSession) -> None:
    """After the session fixture runs, alembic_version holds exactly the one head on disk."""
    assert await _regclass(db, 'public.alembic_version') is not None

    versions = (await db.execute(text('SELECT version_num FROM alembic_version'))).scalars().all()

    assert list(versions) == [_single_migration_head()]


async def test_skeleton_tables_have_the_planned_columns(db: AsyncSession) -> None:
    """Revision 0001 creates accounts, sessions, oauth_states, trips and members."""
    for table, expected in EXPECTED_COLUMNS.items():
        assert await _regclass(db, f'public.{table}') is not None, table
        rows = await db.execute(
            text(
                'SELECT column_name FROM information_schema.columns '
                "WHERE table_schema = 'public' AND table_name = :table"
            ),
            {'table': table},
        )
        assert set(rows.scalars().all()) == expected, table


async def test_account_kind_check_rejects_unknown_values(db: AsyncSession) -> None:
    """accounts.kind only accepts member or persona."""
    assert await _regclass(db, 'public.accounts') is not None

    try:
        await db.execute(text("INSERT INTO accounts (kind, display_name) VALUES ('robot', 'x')"))
    except IntegrityError:
        await db.rollback()
    else:
        raise AssertionError('accounts.kind accepted a value outside (member, persona)')


async def test_trip_name_length_check_rejects_empty_and_overlong_names(db: AsyncSession) -> None:
    """trips.name must be between 1 and 80 characters."""
    assert await _regclass(db, 'public.trips') is not None

    await db.execute(text("INSERT INTO accounts (display_name) VALUES ('Organiser')"))
    account_id = (await db.execute(text('SELECT id FROM accounts'))).scalar_one()
    for bad_name in ('', 'n' * 81):
        try:
            await db.execute(
                text('INSERT INTO trips (name, organiser_account_id) VALUES (:n, :a)'),
                {'n': bad_name, 'a': account_id},
            )
        except IntegrityError:
            await db.rollback()
            await db.execute(text("INSERT INTO accounts (display_name) VALUES ('Organiser')"))
            account_id = (await db.execute(text('SELECT id FROM accounts'))).scalar_one()
        else:
            raise AssertionError(f'trips.name accepted {len(bad_name)} characters')


async def test_procrastinate_schema_is_created_by_revision_0002(db: AsyncSession) -> None:
    """procrastinate_jobs exists because the 0002 revision applied the schema, not a CLI call."""
    assert await _regclass(db, 'public.procrastinate_jobs') is not None


def test_each_test_starts_with_empty_application_tables_part_one(
    sync_conn: Conn, table_helpers: TableHelpers
) -> None:
    """Leave committed rows behind for the next test to prove they are truncated."""
    list_tables, _truncate = table_helpers
    assert 'accounts' in list_tables(sync_conn)
    sync_conn.execute("INSERT INTO accounts (display_name) VALUES ('left behind')")


def test_each_test_starts_with_empty_application_tables_part_two(sync_conn: Conn) -> None:
    """The row committed by part one is gone; alembic_version survived the truncation."""
    count = sync_conn.execute('SELECT count(*) FROM accounts').fetchone()
    assert count is not None
    assert count[0] == 0
    version = sync_conn.execute('SELECT version_num FROM alembic_version').fetchone()
    assert version is not None
    assert version[0] == _single_migration_head()


def test_truncation_list_is_read_from_the_catalog(
    sync_conn: Conn, table_helpers: TableHelpers
) -> None:
    """A table created later is listed and cleared with no edit to the fixture."""
    list_tables, truncate = table_helpers
    sync_conn.execute('CREATE TABLE zz_scratch_late (id int)')
    try:
        sync_conn.execute('INSERT INTO zz_scratch_late VALUES (1)')
        tables = list_tables(sync_conn)
        assert 'zz_scratch_late' in tables
        assert 'alembic_version' not in tables
        assert 'ledger_entries' not in tables

        truncate(sync_conn, tables)

        count = sync_conn.execute('SELECT count(*) FROM zz_scratch_late').fetchone()
        assert count is not None
        assert count[0] == 0
    finally:
        sync_conn.execute('DROP TABLE zz_scratch_late')

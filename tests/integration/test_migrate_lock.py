"""Migrations run under a Postgres advisory lock (01-07, T-01-21).

The lock is database-scoped, so the "second caller waits" proof holds the lock on the test
database itself, and the race proof migrates a scratch database from nothing with two callers.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from psycopg import sql
from sqlalchemy.engine import make_url

from trippilot.settings import get_settings

REPO_ROOT = Path(__file__).resolve().parents[2]
LOCK_KEY = 727001
WAIT_SECONDS = 30.0
SCRATCH_DATABASE = 'trippilot_migrate_lock_test'

Conn = psycopg.Connection[tuple[object, ...]]


def _head() -> str:
    """Return the one Alembic head on disk."""
    heads = ScriptDirectory.from_config(Config(str(REPO_ROOT / 'alembic.ini'))).get_heads()
    assert len(heads) == 1
    return heads[0]


def _connect(url: str, dbname: str | None = None) -> Conn:
    """Open an autocommit psycopg connection described by a SQLAlchemy URL."""
    parsed = make_url(url)
    return psycopg.connect(
        host=parsed.host,
        port=parsed.port,
        user=parsed.username,
        password=parsed.password,
        dbname=dbname or parsed.database,
        autocommit=True,
    )


class Runner(threading.Thread):
    """Runs `run_migrations()` on a thread and keeps its outcome."""

    def __init__(self) -> None:
        super().__init__(daemon=True)
        self.error: BaseException | None = None

    def run(self) -> None:
        """Run the migrations, remembering any exception for the test to assert on."""
        from trippilot.db.migrate import run_migrations

        try:
            run_migrations()
        except BaseException as error:  # noqa: BLE001 - re-asserted by the test, not swallowed
            self.error = error


def _waiters(conn: Conn) -> int:
    """Count sessions waiting (not granted) on the migration advisory lock."""
    row = conn.execute(
        "SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' AND objid = %s AND NOT granted",
        (LOCK_KEY,),
    ).fetchone()
    assert row is not None
    count = row[0]
    assert isinstance(count, int)
    return count


def _wait_for_waiter(conn: Conn, runner: Runner) -> None:
    """Block until the runner shows up as a waiter on the lock, failing fast if it ended."""
    deadline = time.monotonic() + WAIT_SECONDS
    while time.monotonic() < deadline:
        if _waiters(conn):
            return
        assert runner.is_alive(), f'run_migrations ended without waiting: {runner.error!r}'
        time.sleep(0.05)
    raise AssertionError('run_migrations never waited on the advisory lock')


def test_the_lock_key_is_the_documented_constant() -> None:
    """The key is fixed so every deploy contends on the same lock."""
    from trippilot.db.migrate import MIGRATION_LOCK_KEY

    assert MIGRATION_LOCK_KEY == LOCK_KEY


def test_second_caller_waits_while_the_lock_is_held_then_completes(test_database: str) -> None:
    """Hold the lock on one connection: the migration blocks, then finishes after the release."""
    with _connect(test_database) as holder:
        holder.execute('SELECT pg_advisory_lock(%s)', (LOCK_KEY,))
        runner = Runner()
        runner.start()
        try:
            _wait_for_waiter(holder, runner)
            time.sleep(0.5)
            assert runner.is_alive(), 'run_migrations finished while the lock was held'
        finally:
            holder.execute('SELECT pg_advisory_unlock(%s)', (LOCK_KEY,))
        runner.join(WAIT_SECONDS)

    assert not runner.is_alive()
    assert runner.error is None
    with _connect(test_database) as check:
        versions = check.execute('SELECT version_num FROM alembic_version').fetchall()
    assert [row[0] for row in versions] == [_head()]


@pytest.fixture
def scratch_database(test_database: str) -> Iterator[str]:
    """Create an empty scratch database, point Settings at it, and drop it afterwards."""
    name = make_url(test_database).database
    assert name is not None
    scratch = make_url(test_database).set(database=SCRATCH_DATABASE)
    with _connect(test_database, dbname='postgres') as admin:
        quoted = sql.Identifier(SCRATCH_DATABASE)
        admin.execute(sql.SQL('DROP DATABASE IF EXISTS {} WITH (FORCE)').format(quoted))
        admin.execute(sql.SQL('CREATE DATABASE {}').format(quoted))
    url = scratch.render_as_string(hide_password=False)
    mp = pytest.MonkeyPatch()
    mp.setenv('DATABASE_URL', url)
    get_settings.cache_clear()
    try:
        yield url
    finally:
        mp.undo()
        get_settings.cache_clear()
        with _connect(test_database, dbname='postgres') as admin:
            admin.execute(sql.SQL('DROP DATABASE IF EXISTS {} WITH (FORCE)').format(quoted))


def test_two_concurrent_runs_on_an_empty_database_both_finish_with_one_head(
    scratch_database: str,
) -> None:
    """Two callers racing a from-scratch migration serialise on the lock and both succeed."""
    runners = [Runner(), Runner()]
    for runner in runners:
        runner.start()
    for runner in runners:
        runner.join(WAIT_SECONDS * 2)

    assert all(not runner.is_alive() for runner in runners)
    assert [runner.error for runner in runners] == [None, None]
    with _connect(scratch_database) as check:
        versions = check.execute('SELECT version_num FROM alembic_version').fetchall()
    assert [row[0] for row in versions] == [_head()]

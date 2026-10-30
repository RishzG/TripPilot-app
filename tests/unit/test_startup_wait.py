"""The web lifespan waits for a database that is still starting (01-17).

The first production deploy failed because Postgres refused connections while the web process
opened its job-queue pool. `wait_for_database` retries for the same bounded time as the migration
step. psycopg.AsyncConnection.connect is faked here; no database is needed.
"""

from __future__ import annotations

from typing import Any

import psycopg
import pytest

from trippilot.db import migrate, startup


class Clock:
    """A fake monotonic clock whose async sleep advances time instantly."""

    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        """Return the fake time."""
        return self.now

    async def sleep(self, seconds: float) -> None:
        """Advance the fake time."""
        self.sleeps.append(seconds)
        self.now += seconds


class FakeConnection:
    """Records whether the probe connection was closed."""

    def __init__(self) -> None:
        self.closed = False

    async def close(self) -> None:
        """Mark the connection closed."""
        self.closed = True


async def test_waits_until_the_database_accepts_then_closes_the_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two refusals then success: returns after two short waits and closes its connection."""
    clock = Clock()
    attempts: list[str] = []
    connection = FakeConnection()

    async def fake_connect(dsn: str, **kwargs: Any) -> FakeConnection:
        attempts.append(dsn)
        if len(attempts) < 3:
            raise psycopg.OperationalError('connection refused')
        return connection

    monkeypatch.setattr(psycopg.AsyncConnection, 'connect', fake_connect)

    await startup.wait_for_database(
        'postgresql://db/x', sleep=clock.sleep, monotonic=clock.monotonic
    )

    assert attempts == ['postgresql://db/x'] * 3
    assert clock.sleeps == [migrate.CONNECT_RETRY_SECONDS] * 2
    assert connection.closed


async def test_gives_up_after_the_migration_timeout_with_the_last_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A database that never comes up fails startup after the same bounded wait as migrations."""
    clock = Clock()

    async def refuse(dsn: str, **kwargs: Any) -> FakeConnection:
        raise psycopg.OperationalError('connection refused')

    monkeypatch.setattr(psycopg.AsyncConnection, 'connect', refuse)

    with pytest.raises(psycopg.OperationalError, match='connection refused'):
        await startup.wait_for_database(
            'postgresql://db/x', sleep=clock.sleep, monotonic=clock.monotonic
        )

    assert clock.now >= migrate.CONNECT_TIMEOUT_SECONDS
    assert clock.now < migrate.CONNECT_TIMEOUT_SECONDS + migrate.CONNECT_RETRY_SECONDS + 1

"""The migration lock connection waits for a database that is still starting (01-07).

On the first Blueprint deploy Render started the web pre-deploy before the new Postgres accepted
connections ("Connection refused"), so `run_migrations` retries its lock connection for a bounded
time. psycopg.connect is faked here; no database is needed.
"""

from __future__ import annotations

from typing import Any

import psycopg
import pytest

from trippilot.db import migrate


class Clock:
    """A fake monotonic clock whose sleep advances time instantly."""

    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        """Return the fake time."""
        return self.now

    def sleep(self, seconds: float) -> None:
        """Advance the fake time."""
        self.sleeps.append(seconds)
        self.now += seconds


def test_connect_retries_until_the_database_accepts_connections(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two refusals then success: the connection is returned after two short waits."""
    clock = Clock()
    attempts: list[str] = []
    connection = object()

    def fake_connect(dsn: str, **kwargs: Any) -> object:
        attempts.append(dsn)
        if len(attempts) < 3:
            raise psycopg.OperationalError('connection refused')
        assert kwargs == {'autocommit': True}
        return connection

    monkeypatch.setattr(migrate.psycopg, 'connect', fake_connect)

    result = migrate.connect_for_lock(
        'postgresql://db/x', sleep=clock.sleep, monotonic=clock.monotonic
    )

    assert result is connection
    assert attempts == ['postgresql://db/x'] * 3
    assert clock.sleeps == [migrate.CONNECT_RETRY_SECONDS] * 2


def test_connect_gives_up_after_the_timeout_with_the_last_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A database that never comes up fails the deploy after a bounded wait."""
    clock = Clock()

    def refuse(dsn: str, **kwargs: Any) -> object:
        raise psycopg.OperationalError('connection refused')

    monkeypatch.setattr(migrate.psycopg, 'connect', refuse)

    with pytest.raises(psycopg.OperationalError, match='connection refused'):
        migrate.connect_for_lock('postgresql://db/x', sleep=clock.sleep, monotonic=clock.monotonic)

    assert clock.now >= migrate.CONNECT_TIMEOUT_SECONDS
    assert clock.now < migrate.CONNECT_TIMEOUT_SECONDS + migrate.CONNECT_RETRY_SECONDS + 1

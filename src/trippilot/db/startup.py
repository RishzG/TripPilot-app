"""Wait for a database that is still starting before the web process opens its pools (01-17).

The first production deploy failed this way: migrations retried until Postgres accepted
connections, then the database refused connections again while the web process opened the
procrastinate pool, whose own 30-second limit ran out. Production is also suspended and resumed
between uses until Nov 5, so a slow database at startup is expected. The web lifespan therefore
waits as long as the migration step does (`migrate.CONNECT_TIMEOUT_SECONDS`) before opening the
pool.
"""

from __future__ import annotations

import asyncio
import sys
import time
from collections.abc import Awaitable, Callable

import psycopg

from trippilot.db.migrate import CONNECT_RETRY_SECONDS, CONNECT_TIMEOUT_SECONDS


async def wait_for_database(
    dsn: str,
    *,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    monotonic: Callable[[], float] = time.monotonic,
) -> None:
    """Return once one connection to `dsn` succeeds, retrying while the database refuses.

    Raises the last `psycopg.OperationalError` once `CONNECT_TIMEOUT_SECONDS` have passed.
    """
    deadline = monotonic() + CONNECT_TIMEOUT_SECONDS
    while True:
        try:
            connection = await psycopg.AsyncConnection.connect(dsn)
        except psycopg.OperationalError:
            if monotonic() >= deadline:
                raise
            print('startup: database not accepting connections yet; retrying', file=sys.stderr)
            await sleep(CONNECT_RETRY_SECONDS)
        else:
            await connection.close()
            return

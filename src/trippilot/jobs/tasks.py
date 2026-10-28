"""Periodic maintenance tasks run by the worker."""

from __future__ import annotations

import structlog
from sqlalchemy import text

from trippilot.db.engine import get_engine, session_factory
from trippilot.jobs.app import app

logger = structlog.get_logger(__name__)


@app.periodic(cron='*/15 * * * *')
@app.task(queueing_lock='purge_expired_auth_rows')
async def purge_expired_auth_rows(timestamp: int) -> None:
    """Delete oauth_states and sessions rows past their expiry and log how many went."""
    get_engine()
    async with session_factory() as session:
        states = await session.execute(
            text('DELETE FROM oauth_states WHERE expires_at < now() RETURNING 1')
        )
        sessions = await session.execute(
            text('DELETE FROM sessions WHERE expires_at < now() RETURNING 1')
        )
        counts = {'oauth_states': len(states.all()), 'sessions': len(sessions.all())}
        await session.commit()
    logger.info('purged_expired_auth_rows', timestamp=timestamp, **counts)

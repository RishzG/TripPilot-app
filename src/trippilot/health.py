"""Health endpoint: proves the request path reaches Postgres without leaking details."""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, OperationalError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from trippilot.db.engine import get_db
from trippilot.settings import get_settings

router = APIRouter()


class HealthResponse(BaseModel):
    """Body of GET /api/health: status, git sha, database flag and the worker heartbeat age."""

    status: Literal['ok']
    git_sha: str
    db: Literal['ok', 'error']
    worker_last_seen_seconds: float | None


_HEARTBEAT_AGE_SQL = text(
    'SELECT extract(epoch FROM now() - max(last_heartbeat)) FROM procrastinate_workers'
)


async def _worker_last_seen_seconds(session: AsyncSession) -> float | None:
    """Return the age of the newest procrastinate worker heartbeat, or None when unknown.

    The query runs in a savepoint so a failure (for example a missing table) cannot poison the
    request's transaction, and it never turns the health check into an error.
    """
    try:
        async with session.begin_nested():
            age = (await session.execute(_HEARTBEAT_AGE_SQL)).scalar_one()
    except SQLAlchemyError:
        return None
    return None if age is None else float(age)


@router.get('/api/health')
async def health(session: Annotated[AsyncSession, Depends(get_db)]) -> HealthResponse:
    """Run `SELECT 1` through the session dependency; report 'error' without the cause."""
    db_state: Literal['ok', 'error'] = 'ok'
    worker_age: float | None = None
    try:
        await session.execute(text('SELECT 1'))
    except (OperationalError, DBAPIError):
        db_state = 'error'
    else:
        worker_age = await _worker_last_seen_seconds(session)
    return HealthResponse(
        status='ok',
        git_sha=get_settings().app_git_sha,
        db=db_state,
        worker_last_seen_seconds=worker_age,
    )

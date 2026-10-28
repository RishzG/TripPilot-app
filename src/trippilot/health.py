"""Health endpoint: proves the request path reaches Postgres without leaking details."""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from trippilot.db.engine import get_db
from trippilot.settings import get_settings

router = APIRouter()


class HealthResponse(BaseModel):
    """Body of GET /api/health: status, image git sha and a database ok/error flag."""

    status: Literal['ok']
    git_sha: str
    db: Literal['ok', 'error']


@router.get('/api/health')
async def health(session: Annotated[AsyncSession, Depends(get_db)]) -> HealthResponse:
    """Run `SELECT 1` through the session dependency; report 'error' without the cause."""
    db_state: Literal['ok', 'error'] = 'ok'
    try:
        await session.execute(text('SELECT 1'))
    except (OperationalError, DBAPIError):
        db_state = 'error'
    return HealthResponse(status='ok', git_sha=get_settings().app_git_sha, db=db_state)

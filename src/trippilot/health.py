"""Health endpoint: proves the request path reaches Postgres without leaking details."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Annotated, Literal

import httpx
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, OperationalError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from trippilot.contracts.paypal import PayPalError, PayPalGateway
from trippilot.db.engine import get_db
from trippilot.payments import get_paypal_gateway
from trippilot.settings import get_settings

router = APIRouter()

VAULT_SCOPE = 'https://uri.paypal.com/services/vault/payment-tokens/readwrite'
"""The scope a PayPal access token needs to create vault setup and payment tokens."""

PAYPAL_SCOPE_TIMEOUT_SECONDS = 3.0
"""How long /api/health waits for PayPal before reporting the scope check as unknown."""

STARTED_AT = datetime.now(UTC).isoformat(timespec='seconds')
"""Process start time, captured once at import; a restart is visible as a new value."""


class HealthResponse(BaseModel):
    """Body of GET /api/health: status, git sha, database flag, worker heartbeat age, vault scope.

    `paypal_vault_scope` is null when PayPal could not be asked (unreachable or too slow).
    `started_at` is the ISO-8601 UTC time this process started.
    """

    status: Literal['ok']
    git_sha: str
    db: Literal['ok', 'error']
    worker_last_seen_seconds: float | None
    paypal_vault_scope: bool | None
    started_at: str


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


async def _paypal_vault_scope(gateway: PayPalGateway) -> bool | None:
    """Return whether the PayPal token carries the vault scope, or None when it cannot be told.

    PayPal being down, slow or misconfigured must never turn the health check into an error, so
    every failure of the lookup is reported as unknown.
    """
    try:
        scopes = await asyncio.wait_for(
            gateway.access_token_scopes(), timeout=PAYPAL_SCOPE_TIMEOUT_SECONDS
        )
    except (PayPalError, httpx.HTTPError, TimeoutError):
        return None
    return VAULT_SCOPE in scopes


@router.get('/api/health')
async def health(
    session: Annotated[AsyncSession, Depends(get_db)],
    gateway: Annotated[PayPalGateway, Depends(get_paypal_gateway)],
) -> HealthResponse:
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
        paypal_vault_scope=await _paypal_vault_scope(gateway),
        started_at=STARTED_AT,
    )

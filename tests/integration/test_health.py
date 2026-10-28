"""Integration tests for GET /api/health: the tracer path from request to Postgres."""

from __future__ import annotations

import httpx
from fastapi import FastAPI
from sqlalchemy.exc import OperationalError

from trippilot.app import create_app
from trippilot.db.engine import get_db
from trippilot.settings import get_settings


async def test_health_reaches_postgres(client: httpx.AsyncClient) -> None:
    """GET /api/health answers 200 with db 'ok' after a real SELECT 1."""
    response = await client.get('/api/health')

    assert response.status_code == 200
    assert response.json() == {
        'status': 'ok',
        'git_sha': get_settings().app_git_sha,
        'db': 'ok',
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

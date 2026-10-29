"""Integration tests for the worker tier: the auth-row purge task and the heartbeat in health."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from trippilot import health
from trippilot.auth.models import Account, OAuthState, SessionRow
from trippilot.contracts.paypal import PayPalError
from trippilot.jobs.tasks import purge_expired_auth_rows
from trippilot.payments import get_paypal_gateway
from trippilot.payments.fake import VAULT_SCOPE, FakePayPal

if TYPE_CHECKING:
    from conftest import MakeApp, MakeClient


async def test_purge_deletes_expired_auth_rows_and_keeps_live_ones(db: AsyncSession) -> None:
    """Expired sessions and oauth_states rows go; the live session survives."""
    account = Account(kind='member', display_name='Purge Test')
    db.add(account)
    await db.flush()
    for index, interval in enumerate(('1 hour', '-1 hour')):
        expires = (await db.execute(text(f"SELECT now() + interval '{interval}'"))).scalar_one()
        db.add(SessionRow(id_hash=bytes([index]) * 32, account_id=account.id, expires_at=expires))
    expired_state = (await db.execute(text("SELECT now() - interval '1 minute'"))).scalar_one()
    live_state = (await db.execute(text("SELECT now() + interval '10 minutes'"))).scalar_one()
    db.add(OAuthState(state_hash=b'\x01' * 32, expires_at=expired_state))
    db.add(OAuthState(state_hash=b'\x02' * 32, expires_at=live_state))
    await db.commit()

    await purge_expired_auth_rows(0)

    db.expire_all()
    remaining_sessions = (await db.execute(text('SELECT id_hash FROM sessions'))).scalars().all()
    remaining_states = (await db.execute(text('SELECT state_hash FROM oauth_states'))).scalars()
    assert [bytes(row) for row in remaining_sessions] == [bytes([0]) * 32]
    assert [bytes(row) for row in remaining_states] == [b'\x02' * 32]


async def test_health_reports_the_worker_heartbeat_age(
    client: httpx.AsyncClient, db: AsyncSession
) -> None:
    """A heartbeat written 5 seconds ago shows as an age between 0 and 60 seconds."""
    await db.execute(
        text(
            'INSERT INTO procrastinate_workers (last_heartbeat) '
            "VALUES (now() - interval '5 seconds')"
        )
    )
    await db.commit()

    body = (await client.get('/api/health')).json()

    assert set(body) == {
        'status',
        'git_sha',
        'db',
        'worker_last_seen_seconds',
        'paypal_vault_scope',
        'started_at',
    }
    assert body['db'] == 'ok'
    assert 0 <= body['worker_last_seen_seconds'] < 60


async def test_health_reports_null_when_no_worker_is_running(client: httpx.AsyncClient) -> None:
    """With no worker row the heartbeat age is null and the endpoint still answers 200."""
    response = await client.get('/api/health')

    assert response.status_code == 200
    assert response.json()['worker_last_seen_seconds'] is None


async def _health_body(
    make_app: MakeApp, make_client: MakeClient, gateway: object
) -> dict[str, object]:
    """GET /api/health on an app whose PayPal gateway is `gateway`; return the JSON body."""
    app = make_app(False)
    app.dependency_overrides[get_paypal_gateway] = lambda: gateway
    response = await make_client(app).get('/api/health')
    assert response.status_code == 200
    body: dict[str, object] = response.json()
    return body


async def test_health_reports_the_vault_scope_when_the_token_carries_it(
    make_app: MakeApp, make_client: MakeClient
) -> None:
    """The fake's default scopes include the vault payment-token scope, so the flag is true."""
    fake = FakePayPal()
    assert VAULT_SCOPE in fake.scopes

    body = await _health_body(make_app, make_client, fake)

    assert body['paypal_vault_scope'] is True


async def test_health_reports_false_when_the_token_lacks_the_vault_scope(
    make_app: MakeApp, make_client: MakeClient
) -> None:
    """A token without the scope (Pitfall 2) shows as false, not as an error."""
    fake = FakePayPal()
    fake.scopes = ('openid',)

    body = await _health_body(make_app, make_client, fake)

    assert body['paypal_vault_scope'] is False


async def test_health_reports_null_when_paypal_is_unreachable(
    make_app: MakeApp, make_client: MakeClient
) -> None:
    """A PayPal failure makes the flag null while the endpoint still answers 200 with db ok."""
    fake = FakePayPal()
    fake.fail_next('access_token_scopes', PayPalError(503, 'SERVICE_UNAVAILABLE'))

    body = await _health_body(make_app, make_client, fake)

    assert body['paypal_vault_scope'] is None
    assert body['db'] == 'ok'


async def test_health_reports_null_when_the_scope_lookup_times_out(
    make_app: MakeApp, make_client: MakeClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A PayPal call slower than the timeout is abandoned and reported as null."""

    class _Hanging:
        async def access_token_scopes(self) -> tuple[str, ...]:
            await asyncio.sleep(30)
            return ()

    monkeypatch.setattr(health, 'PAYPAL_SCOPE_TIMEOUT_SECONDS', 0.05)

    body = await _health_body(make_app, make_client, _Hanging())

    assert body['paypal_vault_scope'] is None


async def test_health_started_at_is_utc_iso_8601_and_fixed_for_the_process(
    make_app: MakeApp, make_client: MakeClient
) -> None:
    """started_at parses as a UTC timestamp in the past and does not change between requests."""
    first = await _health_body(make_app, make_client, FakePayPal())
    second = await _health_body(make_app, make_client, FakePayPal())

    started = first['started_at']
    assert isinstance(started, str)
    parsed = datetime.fromisoformat(started)
    assert parsed.utcoffset() == timedelta(0)
    assert parsed <= datetime.now(parsed.tzinfo)
    assert second['started_at'] == started

"""Integration tests for the worker tier: the auth-row purge task and the heartbeat in health."""

from __future__ import annotations

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from trippilot.auth.models import Account, OAuthState, SessionRow


async def test_purge_deletes_expired_auth_rows_and_keeps_live_ones(db: AsyncSession) -> None:
    """Expired sessions and oauth_states rows go; the live session survives."""
    from trippilot.jobs.tasks import purge_expired_auth_rows

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

    assert set(body) == {'status', 'git_sha', 'db', 'worker_last_seen_seconds'}
    assert body['db'] == 'ok'
    assert 0 <= body['worker_last_seen_seconds'] < 60


async def test_health_reports_null_when_no_worker_is_running(client: httpx.AsyncClient) -> None:
    """With no worker row the heartbeat age is null and the endpoint still answers 200."""
    response = await client.get('/api/health')

    assert response.status_code == 200
    assert response.json()['worker_last_seen_seconds'] is None

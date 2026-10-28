"""Save, status and remove saved PayPal through the API (plan 01-08, ACC-03), FakePayPal only."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Iterator
from typing import TYPE_CHECKING

import httpx
import psycopg
import pytest
from cryptography.fernet import Fernet
from fastapi import FastAPI
from pydantic import SecretStr

from trippilot.app import create_app
from trippilot.contracts.paypal import PayPalError
from trippilot.payments import get_paypal_gateway
from trippilot.payments.fake import FakePayPal
from trippilot.settings import get_settings

if TYPE_CHECKING:
    from conftest import MakeClient, MakeMember

Conn = psycopg.Connection[tuple[object, ...]]
CLIENT_ID = 'test-client-id-not-a-secret'


def _cookie(raw: str) -> dict[str, str]:
    """Return a Cookie header carrying the raw session value."""
    return {'Cookie': f'tp_session={raw}'}


@pytest.fixture
def fake() -> FakePayPal:
    """Return the fake PayPal every request in a test talks to."""
    return FakePayPal()


@pytest.fixture
def app(fake: FakePayPal) -> Iterator[FastAPI]:
    """Return a demo-mode app with a fresh vault key, FakePayPal and a test client id."""
    settings = get_settings().model_copy(
        update={
            'demo_mode': True,
            'paypal_mode': 'fake',
            'paypal_client_id': CLIENT_ID,
            'vault_keys': SecretStr(Fernet.generate_key().decode()),
        }
    )
    built = create_app(settings)
    built.dependency_overrides[get_paypal_gateway] = lambda: fake
    yield built


async def _save(http: httpx.AsyncClient, raw: str) -> tuple[str, httpx.Response]:
    """Run setup-token then payment-token for the caller; return the setup token and answer."""
    setup = await http.post('/api/paypal/vault/setup-token', headers=_cookie(raw))
    assert setup.status_code == 200, setup.text
    setup_token = str(setup.json()['vaultSetupToken'])
    saved = await http.post(
        '/api/paypal/vault/payment-token',
        json={'vaultSetupToken': setup_token},
        headers=_cookie(raw),
    )
    return setup_token, saved


def _count(conn: Conn, query: str, params: tuple[object, ...] = ()) -> int:
    """Return the integer in the first column of the first row of a query."""
    row = conn.execute(query, params).fetchone()
    assert row is not None
    value = row[0]
    assert isinstance(value, int)
    return value


def _creates(fake: FakePayPal, method: str) -> int:
    return sum(1 for name, _ in fake.calls if name == method)


async def test_config_returns_the_public_client_id_and_environment_only(
    app: FastAPI, make_client: MakeClient
) -> None:
    http = make_client(app)

    response = await http.get('/api/paypal/config')

    assert response.status_code == 200
    assert response.json() == {'clientId': CLIENT_ID, 'environment': 'sandbox'}


async def test_vault_routes_need_a_signed_in_member(app: FastAPI, make_client: MakeClient) -> None:
    http = make_client(app)

    answers = [
        await http.post('/api/paypal/vault/setup-token'),
        await http.post('/api/paypal/vault/payment-token', json={'vaultSetupToken': 'x'}),
        await http.get('/api/paypal/vault/status'),
        await http.delete('/api/paypal/vault'),
    ]

    assert [a.status_code for a in answers] == [401, 401, 401, 401]


async def test_setup_token_is_returned_and_a_pending_row_is_recorded_for_the_caller(
    app: FastAPI, make_client: MakeClient, make_member: MakeMember, sync_conn: Conn
) -> None:
    account, raw = await make_member('Sam')
    http = make_client(app)

    response = await http.post('/api/paypal/vault/setup-token', headers=_cookie(raw))

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {'vaultSetupToken'}
    assert (
        _count(
            sync_conn,
            'SELECT count(*) FROM pending_vault_setups WHERE setup_token_id = %s AND owner_id = %s',
            (body['vaultSetupToken'], account.id),
        )
        == 1
    )


async def test_completing_the_setup_saves_without_exposing_any_token_or_customer_id(
    app: FastAPI,
    make_client: MakeClient,
    make_member: MakeMember,
    fake: FakePayPal,
    sync_conn: Conn,
    caplog: pytest.LogCaptureFixture,
) -> None:
    account, raw = await make_member('Sam')
    http = make_client(app)

    with caplog.at_level(logging.DEBUG):
        _, saved = await _save(http, raw)
        status = await http.get('/api/paypal/vault/status', headers=_cookie(raw))

    assert saved.status_code == 200
    assert saved.json() == {'saved': True}
    assert status.json() == {'saved': True}
    (token,) = fake.payment_tokens.values()
    secrets_ = [token.id, token.customer_id or '']
    rows = sync_conn.execute(
        'SELECT row_to_json(v)::text FROM vault_tokens v WHERE owner_id = %s', (account.id,)
    ).fetchall()
    assert len(rows) == 1
    assert token.payer_id is not None
    assert token.payer_id in str(rows[0][0])
    for secret in secrets_:
        assert secret not in saved.text
        assert secret not in status.text
        assert secret not in str(rows[0][0])
        assert secret not in caplog.text
    ledger = sync_conn.execute(
        'SELECT detail::text, paypal_ids::text FROM ledger_entries WHERE actor_id = %s',
        (str(account.id),),
    ).fetchall()
    assert ledger
    for secret in secrets_:
        assert secret not in repr(ledger)


async def test_another_account_cannot_complete_someone_elses_setup_token(
    app: FastAPI, make_client: MakeClient, make_member: MakeMember, sync_conn: Conn
) -> None:
    _, raw_owner = await make_member('Sam')
    _, raw_other = await make_member('Mallory')
    http = make_client(app)
    setup = await http.post('/api/paypal/vault/setup-token', headers=_cookie(raw_owner))
    token = setup.json()['vaultSetupToken']

    stolen = await http.post(
        '/api/paypal/vault/payment-token',
        json={'vaultSetupToken': token},
        headers=_cookie(raw_other),
    )

    assert stolen.status_code == 403
    assert _count(sync_conn, 'SELECT count(*) FROM vault_tokens') == 0


async def test_an_unknown_or_expired_setup_token_is_404(
    app: FastAPI, make_client: MakeClient, make_member: MakeMember, sync_conn: Conn
) -> None:
    account, raw = await make_member('Sam')
    http = make_client(app)
    setup = await http.post('/api/paypal/vault/setup-token', headers=_cookie(raw))
    token = setup.json()['vaultSetupToken']
    sync_conn.execute(
        "UPDATE pending_vault_setups SET expires_at = now() - interval '1 minute' "
        'WHERE setup_token_id = %s AND owner_id = %s',
        (token, account.id),
    )

    unknown = await http.post(
        '/api/paypal/vault/payment-token',
        json={'vaultSetupToken': f'NOPE-{uuid.uuid4().hex}'},
        headers=_cookie(raw),
    )
    expired = await http.post(
        '/api/paypal/vault/payment-token', json={'vaultSetupToken': token}, headers=_cookie(raw)
    )

    assert unknown.status_code == 404
    assert expired.status_code == 404
    assert _count(sync_conn, 'SELECT count(*) FROM vault_tokens') == 0


async def test_replaying_the_payment_token_call_creates_one_token_and_keeps_one_row(
    app: FastAPI,
    make_client: MakeClient,
    make_member: MakeMember,
    fake: FakePayPal,
    sync_conn: Conn,
) -> None:
    account, raw = await make_member('Sam')
    http = make_client(app)
    setup_token, first = await _save(http, raw)

    replay = await http.post(
        '/api/paypal/vault/payment-token',
        json={'vaultSetupToken': setup_token},
        headers=_cookie(raw),
    )

    assert first.status_code == 200
    assert replay.status_code == 200
    assert _creates(fake, 'create_payment_token') == 1
    assert len(fake.payment_tokens) == 1  # the replay must not delete the token it just saved
    assert (
        _count(
            sync_conn,
            'SELECT count(*) FROM vault_tokens WHERE owner_id = %s AND deleted_at IS NULL',
            (account.id,),
        )
        == 1
    )


async def test_saving_again_deletes_the_superseded_token_at_paypal_and_keeps_one_row(
    app: FastAPI,
    make_client: MakeClient,
    make_member: MakeMember,
    fake: FakePayPal,
    sync_conn: Conn,
) -> None:
    account, raw = await make_member('Sam')
    http = make_client(app)
    await _save(http, raw)
    (first,) = fake.payment_tokens.values()

    _, second = await _save(http, raw)

    assert second.status_code == 200
    assert first.id not in fake.payment_tokens
    assert len(fake.payment_tokens) == 1
    assert _creates(fake, 'delete_payment_token') == 1
    assert (
        _count(
            sync_conn,
            'SELECT count(*) FROM vault_tokens WHERE owner_id = %s AND deleted_at IS NULL',
            (account.id,),
        )
        == 1
    )
    assert (
        _count(sync_conn, 'SELECT count(*) FROM vault_tokens WHERE owner_id = %s', (account.id,))
        == 2
    )


async def test_status_is_private_to_the_caller(
    app: FastAPI, make_client: MakeClient, make_member: MakeMember
) -> None:
    _, raw_saver = await make_member('Sam')
    _, raw_other = await make_member('Riley')
    http = make_client(app)
    await _save(http, raw_saver)

    mine = await http.get('/api/paypal/vault/status', headers=_cookie(raw_saver))
    theirs = await http.get('/api/paypal/vault/status', headers=_cookie(raw_other))

    assert mine.json() == {'saved': True}
    assert theirs.json() == {'saved': False}


async def test_removing_deletes_at_paypal_soft_deletes_our_row_and_writes_the_ledger(
    app: FastAPI,
    make_client: MakeClient,
    make_member: MakeMember,
    fake: FakePayPal,
    sync_conn: Conn,
) -> None:
    account, raw = await make_member('Sam')
    http = make_client(app)
    await _save(http, raw)

    removed = await http.delete('/api/paypal/vault', headers=_cookie(raw))
    status = await http.get('/api/paypal/vault/status', headers=_cookie(raw))

    assert removed.status_code == 200
    assert removed.json() == {'saved': False}
    assert status.json() == {'saved': False}
    assert fake.payment_tokens == {}
    assert (
        _count(
            sync_conn,
            'SELECT count(*) FROM vault_tokens WHERE owner_id = %s AND deleted_at IS NOT NULL',
            (account.id,),
        )
        == 1
    )
    actions = [
        row[0]
        for row in sync_conn.execute(
            'SELECT action FROM ledger_entries WHERE actor_id = %s ORDER BY id', (str(account.id),)
        )
    ]
    assert actions == ['vault.saved', 'vault.removed']


async def test_removing_when_nothing_is_saved_is_a_quiet_no_op(
    app: FastAPI, make_client: MakeClient, make_member: MakeMember, fake: FakePayPal
) -> None:
    _, raw = await make_member('Sam')
    http = make_client(app)

    removed = await http.delete('/api/paypal/vault', headers=_cookie(raw))

    assert removed.status_code == 200
    assert removed.json() == {'saved': False}
    assert _creates(fake, 'delete_payment_token') == 0


async def test_a_paypal_failure_while_removing_keeps_the_saved_token(
    app: FastAPI, make_client: MakeClient, make_member: MakeMember, fake: FakePayPal
) -> None:
    _, raw = await make_member('Sam')
    http = make_client(app)
    await _save(http, raw)
    fake.fail_next('delete_payment_token', PayPalError(500, 'INTERNAL_SERVER_ERROR', 'boom'))

    failed = await http.delete('/api/paypal/vault', headers=_cookie(raw))
    status = await http.get('/api/paypal/vault/status', headers=_cookie(raw))

    assert failed.status_code == 502
    assert status.json() == {'saved': True}
    (token,) = fake.payment_tokens.values()
    assert token.id not in failed.text


async def test_a_paypal_failure_creating_the_setup_token_is_a_502_without_details(
    app: FastAPI, make_client: MakeClient, make_member: MakeMember, fake: FakePayPal
) -> None:
    _, raw = await make_member('Sam')
    http = make_client(app)
    fake.fail_next('create_setup_token', PayPalError(500, 'SECRET_ISSUE', 'internal detail'))

    failed = await http.post('/api/paypal/vault/setup-token', headers=_cookie(raw))

    assert failed.status_code == 502
    assert 'SECRET_ISSUE' not in failed.text
    assert 'internal detail' not in failed.text


async def test_a_persona_session_saves_and_the_ledger_records_a_persona_actor(
    app: FastAPI, make_client: MakeClient, sync_conn: Conn
) -> None:
    http = make_client(app)
    signed_in = await http.post('/api/demo/personas/maya/session')
    assert signed_in.status_code == 200, signed_in.text
    me = await http.get('/api/me')
    account_id = str(me.json()['id'])

    setup = await http.post('/api/paypal/vault/setup-token')
    saved = await http.post(
        '/api/paypal/vault/payment-token', json={'vaultSetupToken': setup.json()['vaultSetupToken']}
    )

    assert saved.status_code == 200
    kinds = [
        row[0]
        for row in sync_conn.execute(
            'SELECT actor_kind FROM ledger_entries WHERE actor_id = %s', (account_id,)
        )
    ]
    assert kinds == ['persona']


async def test_signing_in_and_joining_a_trip_create_no_vault_token(
    app: FastAPI, make_client: MakeClient, make_member: MakeMember, sync_conn: Conn
) -> None:
    _, organiser_raw = await make_member('Olivia')
    _, joiner_raw = await make_member('Jo')
    http = make_client(app)
    trip = await http.post('/api/trips', json={'name': 'Tahoe'}, headers=_cookie(organiser_raw))
    trip_id = trip.json()['id']
    invite = await http.get(f'/api/trips/{trip_id}/invite', headers=_cookie(organiser_raw))
    token = str(invite.json()['url']).rsplit('/join/', 1)[1]

    joined = await http.post(f'/api/invites/{token}/join', headers=_cookie(joiner_raw))
    persona = await make_client(app).post('/api/demo/personas/sam/session')

    assert joined.status_code == 200, joined.text
    assert persona.status_code == 200
    assert _count(sync_conn, 'SELECT count(*) FROM vault_tokens') == 0
    assert _count(sync_conn, 'SELECT count(*) FROM pending_vault_setups') == 0


async def test_a_missing_vault_key_refuses_the_save_instead_of_storing_plaintext(
    fake: FakePayPal, make_client: MakeClient, make_member: MakeMember, sync_conn: Conn
) -> None:
    settings = get_settings().model_copy(
        update={'demo_mode': False, 'paypal_client_id': CLIENT_ID, 'vault_keys': SecretStr('')}
    )
    built = create_app(settings)
    built.dependency_overrides[get_paypal_gateway] = lambda: fake
    _, raw = await make_member('Sam')
    http = make_client(built)
    setup = await http.post('/api/paypal/vault/setup-token', headers=_cookie(raw))
    token = setup.json().get('vaultSetupToken', 'none')

    saved = await http.post(
        '/api/paypal/vault/payment-token', json={'vaultSetupToken': token}, headers=_cookie(raw)
    )

    assert saved.status_code == 503
    assert _count(sync_conn, 'SELECT count(*) FROM vault_tokens') == 0

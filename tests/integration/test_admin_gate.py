"""The team-only Sandbox checks API (plan 01-13, D-37, T-01-39 and T-01-40), FakePayPal not needed.

`ledger_entries` rows persist across tests (01-19), so ledger assertions look up this test's rows
by a unique request id and never count totals.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

import httpx
import psycopg
import pytest
from fastapi import APIRouter, FastAPI
from psycopg.types.json import Jsonb

from trippilot.app import create_app
from trippilot.settings import get_settings

if TYPE_CHECKING:
    from conftest import MakeClient, MakeMember

Conn = psycopg.Connection[tuple[object, ...]]
ADMIN_EMAIL = 'team.lead@example.com'
PATH = '/api/admin/sandbox-checks'
HOLD_ACTIONS = ('hold.placed', 'hold.captured', 'hold.voided', 'vault.token_used')


def _cookie(raw: str) -> dict[str, str]:
    return {'Cookie': f'tp_session={raw}'}


def _app(*, demo_mode: bool = False) -> FastAPI:
    settings = get_settings().model_copy(
        update={'admin_emails': [ADMIN_EMAIL], 'demo_mode': demo_mode}
    )
    return create_app(settings)


def _set_email(conn: Conn, account_id: object, email: str) -> None:
    conn.execute('UPDATE accounts SET email = %s WHERE id = %s', (email, account_id))


def _ledger(
    conn: Conn,
    *,
    action: str,
    request_id: str,
    paypal_ids: dict[str, Any] | None = None,
    amount_cents: int | None = None,
    detail: dict[str, Any] | None = None,
) -> None:
    conn.execute(
        'INSERT INTO ledger_entries (actor_kind, action, request_id, paypal_ids, amount_cents,'
        ' detail) VALUES (%s, %s, %s, %s, %s, %s)',
        (
            'script',
            action,
            request_id,
            Jsonb(paypal_ids or {}),
            amount_cents,
            Jsonb(detail or {}),
        ),
    )


async def test_an_admin_member_gets_200_whatever_the_email_case(
    make_client: MakeClient, make_member: MakeMember, sync_conn: Conn
) -> None:
    account, raw = await make_member('Lead')
    _set_email(sync_conn, account.id, ADMIN_EMAIL.upper())
    http = make_client(_app())

    response = await http.get(PATH, headers=_cookie(raw))

    assert response.status_code == 200, response.text
    assert set(response.json()) == {'holds', 'webhooks'}


async def test_a_member_outside_the_list_gets_403(
    make_client: MakeClient, make_member: MakeMember, sync_conn: Conn
) -> None:
    account, raw = await make_member('Other')
    _set_email(sync_conn, account.id, 'someone.else@example.com')
    http = make_client(_app())

    response = await http.get(PATH, headers=_cookie(raw))

    assert response.status_code == 403


async def test_a_member_with_no_email_gets_403(
    make_client: MakeClient, make_member: MakeMember
) -> None:
    _, raw = await make_member('No email')
    http = make_client(_app())

    response = await http.get(PATH, headers=_cookie(raw))

    assert response.status_code == 403


async def test_a_persona_session_gets_403_even_when_its_email_matches(
    make_client: MakeClient, sync_conn: Conn
) -> None:
    http = make_client(_app(demo_mode=True))
    signed_in = await http.post('/api/demo/personas/maya/session')
    assert signed_in.status_code == 200, signed_in.text
    sync_conn.execute("UPDATE accounts SET email = %s WHERE persona_slug = 'maya'", (ADMIN_EMAIL,))

    response = await http.get(PATH)

    assert response.status_code == 403


async def test_a_member_session_flagged_as_persona_gets_403_too(
    make_client: MakeClient, make_member: MakeMember, sync_conn: Conn
) -> None:
    account, raw = await make_member('Lead')
    _set_email(sync_conn, account.id, ADMIN_EMAIL)
    sync_conn.execute('UPDATE sessions SET is_persona = true WHERE account_id = %s', (account.id,))
    http = make_client(_app())

    response = await http.get(PATH, headers=_cookie(raw))

    assert response.status_code == 403


async def test_signed_out_gets_401(make_client: MakeClient) -> None:
    http = make_client(_app())

    response = await http.get(PATH)

    assert response.status_code == 401


async def test_the_page_lists_this_tests_hold_rows_and_webhook_events(
    make_client: MakeClient, make_member: MakeMember, sync_conn: Conn
) -> None:
    account, raw = await make_member('Lead')
    _set_email(sync_conn, account.id, ADMIN_EMAIL)
    unique = uuid.uuid4().hex
    auth_id = f'AUTH-{unique}'
    _ledger(
        sync_conn,
        action='hold.placed',
        request_id=f'placed-{unique}',
        paypal_ids={'authorization_id': auth_id},
        amount_cents=100,
        detail={
            'status': 'CREATED',
            'expiration_time': '2026-11-27T12:00:00Z',
            'customer_id': 'must-not-be-echoed',
        },
    )
    _ledger(
        sync_conn,
        action='vault.token_used',
        request_id=f'token-{unique}',
        detail={'purpose': 'spike hold'},
    )
    _ledger(sync_conn, action='trip.created', request_id=f'other-{unique}')
    sync_conn.execute(
        'INSERT INTO webhook_events (event_id, event_type, resource_id, verification_status)'
        " VALUES (%s, 'PAYMENT.AUTHORIZATION.CREATED', %s, 'SUCCESS')",
        (f'WH-{unique}', auth_id),
    )
    http = make_client(_app())

    response = await http.get(PATH, headers=_cookie(raw))

    assert response.status_code == 200
    body = response.json()
    holds = {row['request_id']: row for row in body['holds']}
    placed = holds[f'placed-{unique}']
    assert placed['action'] == 'hold.placed'
    assert placed['authorization_id'] == auth_id
    assert placed['status'] == 'CREATED'
    assert placed['amount_cents'] == 100
    assert placed['expires_at'] == '2026-11-27T12:00:00Z'
    token = holds[f'token-{unique}']
    assert token['action'] == 'vault.token_used'
    assert token['authorization_id'] is None
    assert f'other-{unique}' not in holds
    assert 'must-not-be-echoed' not in response.text
    hooks = {row['event_id']: row for row in body['webhooks']}
    hook = hooks[f'WH-{unique}']
    assert hook['event_type'] == 'PAYMENT.AUTHORIZATION.CREATED'
    assert hook['resource_id'] == auth_id
    assert hook['verification_status'] == 'SUCCESS'
    assert hook['received_at'] is not None
    assert hook['processed_at'] is None
    assert {row['action'] for row in body['holds']} <= set(HOLD_ACTIONS)


async def test_the_page_returns_at_most_the_latest_fifty_of_each(
    make_client: MakeClient, make_member: MakeMember, sync_conn: Conn
) -> None:
    account, raw = await make_member('Lead')
    _set_email(sync_conn, account.id, ADMIN_EMAIL)
    unique = uuid.uuid4().hex
    for index in range(55):
        _ledger(sync_conn, action='hold.voided', request_id=f'bulk-{unique}-{index:02d}')
        sync_conn.execute(
            'INSERT INTO webhook_events (event_id, event_type, verification_status)'
            " VALUES (%s, 'PAYMENT.AUTHORIZATION.VOIDED', 'SUCCESS')",
            (f'WH-bulk-{unique}-{index:02d}',),
        )
    http = make_client(_app())

    body = (await http.get(PATH, headers=_cookie(raw))).json()

    assert len(body['holds']) == 50
    assert len(body['webhooks']) == 50
    assert body['holds'][0]['request_id'] == f'bulk-{unique}-54'  # newest first
    assert body['webhooks'][0]['event_id'] == f'WH-bulk-{unique}-54'


def _methods(router: APIRouter) -> set[str]:
    """Return every HTTP method of every route registered on the router, including nested ones."""
    found: set[str] = set()
    for route in router.routes:
        original = getattr(route, 'original_router', None)
        if isinstance(original, APIRouter):
            found |= _methods(original)
        found |= set(getattr(route, 'methods', None) or ())
    return found


def test_every_route_under_api_admin_is_get_only() -> None:
    from trippilot.admin import router as admin_router

    own = _methods(admin_router.router)
    document = _app().openapi()['paths']
    admin_paths = {path: spec for path, spec in document.items() if path.startswith('/api/admin')}

    assert own <= {'GET'}
    assert admin_paths, 'the admin API must be mounted'
    for path, spec in admin_paths.items():
        assert set(spec) == {'get'}, f'{path} offers {sorted(spec)}'


@pytest.mark.parametrize('method', ['POST', 'PUT', 'PATCH', 'DELETE'])
async def test_unsafe_methods_on_the_admin_path_are_not_allowed(
    make_client: MakeClient, make_member: MakeMember, sync_conn: Conn, method: str
) -> None:
    account, raw = await make_member('Lead')
    _set_email(sync_conn, account.id, ADMIN_EMAIL)
    http: httpx.AsyncClient = make_client(_app())

    response = await http.request(method, PATH, headers=_cookie(raw))

    assert response.status_code == 405

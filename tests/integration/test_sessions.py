"""Sliding sessions, sign-out-everywhere and the Origin check (plan 01-12, ACC-04, T-01-35)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import httpx
import psycopg
import pytest
import time_machine
from fastapi import FastAPI

from trippilot.app import create_app
from trippilot.auth.sessions import create_session
from trippilot.settings import get_settings

if TYPE_CHECKING:
    from conftest import MakeClient, MakeMember

Conn = psycopg.Connection[tuple[object, ...]]

PUBLIC_BASE_URL = 'http://localhost:8000'
EVIL = 'https://evil.example'
DEV_ORIGINS = ('http://localhost:5173', 'http://127.0.0.1:5173')


def _cookie(raw: str) -> dict[str, str]:
    """Return a Cookie header carrying the raw session value."""
    return {'Cookie': f'tp_session={raw}'}


def _scalar(conn: Conn, query: str, params: tuple[Any, ...] = ()) -> Any:
    """Return the first column of the first row of a query."""
    row = conn.execute(query, params).fetchone()
    assert row is not None
    return row[0]


def _build(**overrides: object) -> FastAPI:
    """Return a non-demo app whose settings are the test settings plus the overrides."""
    settings = get_settings().model_copy(
        update={'demo_mode': False, 'public_base_url': PUBLIC_BASE_URL, **overrides}
    )
    return create_app(settings)


@pytest.fixture
def app() -> FastAPI:
    """Return a local non-demo app."""
    return _build(app_env='local')


def _expires_at(conn: Conn, raw: str) -> datetime:
    """Return the stored expiry of the session holding this raw cookie value."""
    from trippilot.auth.sessions import hash_token

    value = _scalar(conn, 'SELECT expires_at FROM sessions WHERE id_hash = %s', (hash_token(raw),))
    assert isinstance(value, datetime)
    return value


def _set_cookie_lines(response: httpx.Response) -> list[str]:
    """Return the Set-Cookie header lines of a response."""
    return response.headers.get_list('set-cookie')


async def test_activity_after_an_hour_extends_the_session_and_reissues_the_cookie(
    app: FastAPI, make_client: MakeClient, make_member: MakeMember, sync_conn: Conn
) -> None:
    _, raw = await make_member('Jo Joiner')
    http = make_client(app)
    later = datetime.now(UTC) + timedelta(hours=2)

    with time_machine.travel(later, tick=True):
        response = await http.get('/api/me', headers=_cookie(raw))

    assert response.status_code == 200
    lines = [line for line in _set_cookie_lines(response) if line.startswith('tp_session=')]
    assert len(lines) == 1
    assert lines[0].startswith(f'tp_session={raw};')
    assert 'max-age=2592000' in lines[0].lower()
    assert abs(_expires_at(sync_conn, raw) - (later + timedelta(days=30))) < timedelta(minutes=5)


async def test_activity_within_the_hour_leaves_the_session_alone(
    app: FastAPI, make_client: MakeClient, make_member: MakeMember, sync_conn: Conn
) -> None:
    _, raw = await make_member('Jo Joiner')
    http = make_client(app)
    before = _expires_at(sync_conn, raw)

    with time_machine.travel(datetime.now(UTC) + timedelta(minutes=20), tick=True):
        response = await http.get('/api/me', headers=_cookie(raw))

    assert response.status_code == 200
    assert not [line for line in _set_cookie_lines(response) if line.startswith('tp_session=')]
    assert _expires_at(sync_conn, raw) == before


async def test_a_session_past_its_expiry_is_rejected(
    app: FastAPI, make_client: MakeClient, make_member: MakeMember
) -> None:
    _, raw = await make_member('Jo Joiner')
    http = make_client(app)

    with time_machine.travel(datetime.now(UTC) + timedelta(days=31), tick=True):
        response = await http.get('/api/me', headers=_cookie(raw))

    assert response.status_code == 401


async def test_regular_use_keeps_a_session_alive_beyond_thirty_days(
    app: FastAPI, make_client: MakeClient, make_member: MakeMember
) -> None:
    _, raw = await make_member('Jo Joiner')
    http = make_client(app)
    start = datetime.now(UTC)

    with time_machine.travel(start + timedelta(days=20), tick=True):
        assert (await http.get('/api/me', headers=_cookie(raw))).status_code == 200
    with time_machine.travel(start + timedelta(days=45), tick=True):
        alive = await http.get('/api/me', headers=_cookie(raw))
    with time_machine.travel(start + timedelta(days=90), tick=True):
        gone = await http.get('/api/me', headers=_cookie(raw))

    assert alive.status_code == 200
    assert gone.status_code == 401


async def test_sign_out_everywhere_ends_every_session_of_the_account_only(
    app: FastAPI, make_client: MakeClient, make_member: MakeMember, sync_conn: Conn
) -> None:
    from trippilot.db.engine import get_engine, session_factory

    account, first_raw = await make_member('Jo Joiner')
    _, other_raw = await make_member('Olivia Organiser')
    get_engine()
    async with session_factory() as db:
        second_raw = await create_session(db, account.id, is_persona=False, user_agent='phone')
        await db.commit()
    http = make_client(app)

    response = await http.post('/api/auth/signout-everywhere', headers=_cookie(first_raw))

    assert response.status_code == 204
    assert any(
        line.startswith('tp_session=') and 'max-age=0' in line.lower()
        for line in _set_cookie_lines(response)
    )
    assert (
        _scalar(sync_conn, 'SELECT count(*) FROM sessions WHERE account_id = %s', (account.id,))
        == 0
    )
    assert (await http.get('/api/me', headers=_cookie(first_raw))).status_code == 401
    assert (await http.get('/api/me', headers=_cookie(second_raw))).status_code == 401
    assert (await http.get('/api/me', headers=_cookie(other_raw))).status_code == 200


async def test_sign_out_everywhere_needs_a_session(app: FastAPI, make_client: MakeClient) -> None:
    http = make_client(app)

    response = await http.post('/api/auth/signout-everywhere')

    assert response.status_code == 401


# -- Origin check ---------------------------------------------------------------------------


async def _post_trip(
    http: httpx.AsyncClient, raw: str, headers: dict[str, str] | None = None
) -> httpx.Response:
    """POST /api/trips as the session holder with extra headers."""
    return await http.post(
        '/api/trips', json={'name': 'Tahoe weekend'}, headers={**_cookie(raw), **(headers or {})}
    )


async def test_a_foreign_origin_on_an_unsafe_api_request_is_refused_before_it_runs(
    app: FastAPI, make_client: MakeClient, make_member: MakeMember, sync_conn: Conn
) -> None:
    _, raw = await make_member('Olivia Organiser')
    http = make_client(app)

    response = await _post_trip(http, raw, {'Origin': EVIL})

    assert response.status_code == 403
    assert _scalar(sync_conn, 'SELECT count(*) FROM trips') == 0


@pytest.mark.parametrize(
    'headers',
    [
        {'Origin': PUBLIC_BASE_URL},
        {'Referer': f'{PUBLIC_BASE_URL}/trips/new'},
        {},
    ],
)
async def test_the_public_origin_a_same_site_referer_or_no_header_passes(
    app: FastAPI, make_client: MakeClient, make_member: MakeMember, headers: dict[str, str]
) -> None:
    _, raw = await make_member('Olivia Organiser')
    http = make_client(app)

    response = await _post_trip(http, raw, headers)

    assert response.status_code == 201, response.text


@pytest.mark.parametrize(
    'headers',
    [
        {'Referer': f'{EVIL}/page'},
        {'Origin': 'null'},
        {'Origin': 'http://localhost:8000.evil.example'},
        {'Origin': 'https://localhost:8000'},
    ],
)
async def test_a_foreign_referer_a_null_origin_or_a_lookalike_is_refused(
    app: FastAPI, make_client: MakeClient, make_member: MakeMember, headers: dict[str, str]
) -> None:
    _, raw = await make_member('Olivia Organiser')
    http = make_client(app)

    response = await _post_trip(http, raw, headers)

    assert response.status_code == 403


async def test_a_trailing_slash_on_the_public_base_url_does_not_matter(
    make_client: MakeClient, make_member: MakeMember
) -> None:
    app = _build(app_env='local', public_base_url=f'{PUBLIC_BASE_URL}/')
    _, raw = await make_member('Olivia Organiser')
    http = make_client(app)

    response = await _post_trip(http, raw, {'Origin': PUBLIC_BASE_URL})

    assert response.status_code == 201


async def test_safe_methods_are_not_checked(
    app: FastAPI, make_client: MakeClient, make_member: MakeMember
) -> None:
    _, raw = await make_member('Olivia Organiser')
    http = make_client(app)

    response = await http.get('/api/me', headers={**_cookie(raw), 'Origin': EVIL})

    assert response.status_code == 200


async def test_the_paypal_webhook_path_is_exempt_from_the_origin_check(
    app: FastAPI, make_client: MakeClient
) -> None:
    http = make_client(app)

    response = await http.post('/api/paypal/webhooks', content=b'{}', headers={'Origin': EVIL})

    assert response.status_code != 403


@pytest.mark.parametrize('origin', DEV_ORIGINS)
async def test_the_vite_dev_origins_pass_only_when_the_app_env_is_local(
    make_client: MakeClient, make_member: MakeMember, origin: str
) -> None:
    _, raw = await make_member('Olivia Organiser')
    local = make_client(_build(app_env='local'))

    response = await _post_trip(local, raw, {'Origin': origin})

    assert response.status_code == 201, response.text


@pytest.mark.parametrize('origin', DEV_ORIGINS)
@pytest.mark.parametrize('env', ['staging', 'production', 'test'])
async def test_the_vite_dev_origins_are_refused_outside_local(
    make_client: MakeClient, make_member: MakeMember, origin: str, env: str
) -> None:
    _, raw = await make_member('Olivia Organiser')
    http = make_client(_build(app_env=env, public_base_url='https://staging.example.test'))

    refused = await _post_trip(http, raw, {'Origin': origin})
    allowed = await _post_trip(http, raw, {'Origin': 'https://staging.example.test'})

    assert refused.status_code == 403
    assert allowed.status_code == 201

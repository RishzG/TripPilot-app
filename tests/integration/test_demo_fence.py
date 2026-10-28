"""Sessions, /api/me, sign-out (D-03) and the demo persona fence (D-13, D-15).

The persona cases are added by plan 01-20 task 2; this module starts with the session store.
"""

from __future__ import annotations

import base64
import hashlib
from typing import TYPE_CHECKING

import psycopg
from fastapi import Response

if TYPE_CHECKING:
    from conftest import MakeApp, MakeClient, MakeMember


Conn = psycopg.Connection[tuple[object, ...]]


def _cookie(raw: str) -> dict[str, str]:
    """Return a Cookie header carrying the raw session value."""
    return {'Cookie': f'tp_session={raw}'}


def _count(conn: Conn, table: str) -> int:
    """Return the row count of an application table."""
    row = conn.execute(f'SELECT count(*) FROM {table}').fetchone()  # noqa: S608
    assert row is not None
    return int(str(row[0]))


async def test_me_returns_the_member_profile(
    make_app: MakeApp, make_client: MakeClient, make_member: MakeMember
) -> None:
    account, raw = await make_member('Riya Test')
    http = make_client(make_app(False))

    response = await http.get('/api/me', headers=_cookie(raw))

    assert response.status_code == 200
    assert response.json() == {
        'id': str(account.id),
        'display_name': 'Riya Test',
        'nickname': None,
        'avatar_kind': 'initials',
        'avatar_key': None,
        'kind': 'member',
        'is_persona': False,
    }


async def test_session_row_stores_only_the_sha256_hash(
    make_member: MakeMember, sync_conn: Conn
) -> None:
    account, raw = await make_member()

    rows = sync_conn.execute('SELECT * FROM sessions').fetchall()
    assert len(rows) == 1
    columns = [col.name for col in (sync_conn.execute('SELECT * FROM sessions').description or [])]
    row = dict(zip(columns, rows[0], strict=True))

    assert isinstance(row['id_hash'], bytes)
    assert len(row['id_hash']) == 32
    assert row['id_hash'] == hashlib.sha256(raw.encode()).digest()
    assert row['account_id'] == account.id
    assert row['is_persona'] is False
    # the raw cookie value appears in no column of any sessions row
    for value in row.values():
        assert raw not in str(value)
        if isinstance(value, bytes):
            assert raw.encode() not in value


async def test_session_token_is_256_bit_urlsafe(make_member: MakeMember) -> None:
    _, raw = await make_member()

    padded = raw + '=' * (-len(raw) % 4)
    assert len(base64.urlsafe_b64decode(padded)) == 32


async def test_hash_token_is_the_sha256_digest() -> None:
    from trippilot.auth.sessions import hash_token

    assert hash_token('abc') == hashlib.sha256(b'abc').digest()
    assert len(hash_token('abc')) == 32


async def test_me_without_a_cookie_is_401(make_app: MakeApp, make_client: MakeClient) -> None:
    http = make_client(make_app(False))

    response = await http.get('/api/me')

    assert response.status_code == 401


async def test_me_with_an_unknown_cookie_is_401(make_app: MakeApp, make_client: MakeClient) -> None:
    http = make_client(make_app(False))

    response = await http.get('/api/me', headers=_cookie('not-a-real-session'))

    assert response.status_code == 401


async def test_me_with_an_expired_session_is_401(
    make_app: MakeApp, make_client: MakeClient, make_member: MakeMember, sync_conn: Conn
) -> None:
    _, raw = await make_member()
    sync_conn.execute("UPDATE sessions SET expires_at = now() - interval '1 minute'")
    http = make_client(make_app(False))

    response = await http.get('/api/me', headers=_cookie(raw))

    assert response.status_code == 401


async def test_signout_deletes_the_row_and_clears_the_cookie(
    make_app: MakeApp, make_client: MakeClient, make_member: MakeMember, sync_conn: Conn
) -> None:
    _, raw = await make_member()
    http = make_client(make_app(False))
    assert (await http.get('/api/me', headers=_cookie(raw))).status_code == 200

    response = await http.post('/api/auth/signout', headers=_cookie(raw))

    assert response.status_code == 204
    set_cookie = response.headers['set-cookie'].lower()
    assert 'tp_session=' in set_cookie
    assert 'max-age=0' in set_cookie
    assert _count(sync_conn, 'sessions') == 0
    assert (await http.get('/api/me', headers=_cookie(raw))).status_code == 401


async def test_signout_without_a_session_is_still_204(
    make_app: MakeApp, make_client: MakeClient
) -> None:
    http = make_client(make_app(False))

    response = await http.post('/api/auth/signout')

    assert response.status_code == 204


async def test_session_cookie_flags_follow_the_environment() -> None:
    from trippilot.auth.sessions import clear_session_cookie, set_session_cookie

    from trippilot.settings import get_settings

    base = get_settings()
    flags: dict[str, str] = {}
    for env in ('local', 'test', 'staging', 'production'):
        response = Response()
        set_session_cookie(response, 'raw-value', base.model_copy(update={'app_env': env}))
        flags[env] = response.headers['set-cookie'].lower()

    for env, header in flags.items():
        assert 'tp_session=raw-value' in header
        assert 'httponly' in header
        assert 'samesite=lax' in header
        assert 'path=/' in header
        assert 'max-age=2592000' in header
        assert ('secure' in header.replace('samesite', '')) is (env in ('staging', 'production'))

    cleared = Response()
    clear_session_cookie(cleared)
    clearing = cleared.headers['set-cookie'].lower()
    assert 'max-age=0' in clearing
    assert 'httponly' in clearing
    assert 'samesite=lax' in clearing

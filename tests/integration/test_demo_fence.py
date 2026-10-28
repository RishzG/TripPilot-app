"""Sessions, /api/me, sign-out (D-03) and the demo persona fence (D-13, D-15).

The persona cases are added by plan 01-20 task 2; this module starts with the session store.
"""

from __future__ import annotations

import base64
import hashlib
from typing import TYPE_CHECKING

import httpx
import psycopg
from fastapi import Response

if TYPE_CHECKING:
    from conftest import MakeApp, MakeClient, MakeMember, PersonaClient


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


async def test_persona_list_has_the_fixed_cast_of_six(
    make_app: MakeApp, make_client: MakeClient
) -> None:
    http = make_client(make_app(True))

    response = await http.get('/api/demo/personas')

    assert response.status_code == 200
    personas = response.json()
    assert [(p['slug'], p['name'], p['avatar_key'], p['note']) for p in personas] == [
        ('maya', 'Maya', 'maya', 'tight budget'),
        ('sam', 'Sam', 'sam', 'wants adventure'),
        ('ana', 'Ana', 'ana', 'foodie, flexible dates'),
        ('leo', 'Leo', 'leo', 'last-minute planner'),
        ('priya', 'Priya', 'priya', 'organised, loves cabins'),
        ('jules', 'Jules', 'jules', 'joins late, easygoing'),
    ]


async def test_persona_sign_in_sets_an_http_only_lax_cookie(
    make_app: MakeApp, make_client: MakeClient
) -> None:
    http = make_client(make_app(True))

    response = await http.post('/api/demo/personas/maya/session')

    assert response.status_code == 200
    set_cookie = response.headers['set-cookie'].lower()
    assert 'tp_session=' in set_cookie
    assert 'httponly' in set_cookie
    assert 'samesite=lax' in set_cookie
    assert response.json()['kind'] == 'persona'
    assert response.json()['is_persona'] is True
    assert response.json()['display_name'] == 'Maya'


async def test_persona_account_and_session_are_flagged_and_reused(
    persona_client: PersonaClient, sync_conn: Conn
) -> None:
    await persona_client('maya')
    await persona_client('maya')

    accounts = sync_conn.execute(
        'SELECT kind, persona_slug, display_name, avatar_kind, avatar_key FROM accounts'
    ).fetchall()
    assert accounts == [('persona', 'maya', 'Maya', 'illustrated', 'maya')]
    sessions = sync_conn.execute('SELECT is_persona FROM sessions').fetchall()
    assert sessions == [(True,), (True,)]


async def test_persona_cookie_authenticates_a_fresh_client(
    persona_client: PersonaClient, make_app: MakeApp, make_client: MakeClient
) -> None:
    signed_in = await persona_client('sam')
    raw = signed_in.cookies.get('tp_session')
    assert raw is not None
    fresh = make_client(make_app(True))

    response = await fresh.get('/api/me', headers=_cookie(raw))

    assert response.status_code == 200
    assert response.json()['kind'] == 'persona'
    assert response.json()['is_persona'] is True
    assert response.json()['display_name'] == 'Sam'


async def test_switching_persona_is_signing_in_as_another(
    persona_client: PersonaClient, sync_conn: Conn
) -> None:
    maya = await persona_client('maya')
    sam = await persona_client('sam')

    assert (await maya.get('/api/me')).json()['display_name'] == 'Maya'
    assert (await sam.get('/api/me')).json()['display_name'] == 'Sam'
    assert _count(sync_conn, 'accounts') == 2


async def test_unknown_persona_slug_is_404(make_app: MakeApp, make_client: MakeClient) -> None:
    http = make_client(make_app(True))

    response = await http.post('/api/demo/personas/nobody/session')

    assert response.status_code == 404


async def test_demo_routes_do_not_exist_when_demo_mode_is_off(
    make_app: MakeApp, make_client: MakeClient, sync_conn: Conn
) -> None:
    app = make_app(False)
    http = make_client(app)

    listing = await http.get('/api/demo/personas')
    sign_in = await http.post('/api/demo/personas/maya/session')

    assert listing.status_code == 404
    assert sign_in.status_code == 404
    assert 'set-cookie' not in sign_in.headers
    assert not any(str(getattr(route, 'path', '')).startswith('/api/demo') for route in app.routes)
    assert _count(sync_conn, 'accounts') == 0
    assert _count(sync_conn, 'sessions') == 0


async def _non_demo_trip_with_member_row(
    sync_conn: Conn, make_member: MakeMember, persona_http: httpx.AsyncClient
) -> str:
    """Insert a non-demo trip organised by a member plus an ACTIVE membership for the persona."""
    organiser, _ = await make_member('Olivia Organiser')
    persona_id = (await persona_http.get('/api/me')).json()['id']
    row = sync_conn.execute(
        'INSERT INTO trips (name, organiser_account_id, demo_mode) VALUES (%s, %s, false)'
        ' RETURNING id',
        ('Real trip', organiser.id),
    ).fetchone()
    assert row is not None
    trip_id = str(row[0])
    sync_conn.execute(
        "INSERT INTO members (trip_id, account_id, role) VALUES (%s, %s, 'organiser')",
        (trip_id, organiser.id),
    )
    sync_conn.execute(
        'INSERT INTO members (trip_id, account_id, role, status)'
        " VALUES (%s, %s, 'member', 'active')",
        (trip_id, persona_id),
    )
    return trip_id


async def test_a_persona_lists_only_demo_trips(
    persona_client: PersonaClient, make_member: MakeMember, sync_conn: Conn
) -> None:
    maya = await persona_client('maya')
    demo_trip = (await maya.post('/api/trips', json={'name': 'Demo trip'})).json()['id']
    real_trip = await _non_demo_trip_with_member_row(sync_conn, make_member, maya)

    response = await maya.get('/api/trips')

    assert response.status_code == 200
    ids = [trip['id'] for trip in response.json()]
    assert ids == [demo_trip]
    assert real_trip not in ids
    assert response.json()[0]['demo_mode'] is True


async def test_a_persona_cannot_open_a_non_demo_trip_even_with_a_membership_row(
    persona_client: PersonaClient, make_member: MakeMember, sync_conn: Conn
) -> None:
    maya = await persona_client('maya')
    real_trip = await _non_demo_trip_with_member_row(sync_conn, make_member, maya)

    response = await maya.get(f'/api/trips/{real_trip}')

    assert response.status_code == 404


async def test_a_persona_cannot_join_a_non_demo_trip_through_its_link(
    persona_client: PersonaClient,
    make_member: MakeMember,
    make_app: MakeApp,
    make_client: MakeClient,
    sync_conn: Conn,
) -> None:
    _, organiser_raw = await make_member('Olivia Organiser')
    member_http = make_client(make_app(False))
    created = await member_http.post(
        '/api/trips', json={'name': 'Real trip'}, headers=_cookie(organiser_raw)
    )
    trip_id = created.json()['id']
    link = await member_http.get(f'/api/trips/{trip_id}/invite', headers=_cookie(organiser_raw))
    token = link.json()['url'].rsplit('/join/', 1)[1]
    sam = await persona_client('sam')

    response = await sam.post(f'/api/invites/{token}/join')

    assert response.status_code == 404
    row = sync_conn.execute(
        'SELECT count(*) FROM members WHERE trip_id = %s', (trip_id,)
    ).fetchone()
    assert row is not None
    assert row[0] == 1


async def test_a_persona_cannot_use_the_controls_of_a_non_demo_trip(
    persona_client: PersonaClient, make_member: MakeMember, sync_conn: Conn
) -> None:
    maya = await persona_client('maya')
    real_trip = await _non_demo_trip_with_member_row(sync_conn, make_member, maya)

    invite = await maya.get(f'/api/trips/{real_trip}/invite')
    leave = await maya.post(f'/api/trips/{real_trip}/leave')

    assert invite.status_code == 404
    assert leave.status_code == 404

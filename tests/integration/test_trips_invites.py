"""Invite link to joined member (plan 01-05, ACC-01 and ACC-02): the reusable link, the join."""

from __future__ import annotations

import asyncio
import hashlib
from typing import TYPE_CHECKING, Any

import httpx
import psycopg
import pytest
from fastapi import FastAPI

from trippilot.trips.invites import invite_rate_limit

if TYPE_CHECKING:
    from conftest import MakeApp, MakeClient, MakeMember, PersonaClient


Conn = psycopg.Connection[tuple[object, ...]]


def _cookie(raw: str) -> dict[str, str]:
    """Return a Cookie header carrying the raw session value."""
    return {'Cookie': f'tp_session={raw}'}


async def _no_limit() -> None:
    """Stand-in for the per-IP limiter, so tests that legitimately exceed it can run."""


@pytest.fixture
def app(make_app: MakeApp) -> FastAPI:
    """Return a non-demo app whose invite rate limit is switched off."""
    built = make_app(False)
    built.dependency_overrides[invite_rate_limit] = _no_limit
    return built


def _token_of(url: str) -> str:
    """Return the raw token at the end of an invite URL."""
    assert '/join/' in url
    return url.rsplit('/join/', 1)[1]


def _scalar(conn: Conn, query: str, params: tuple[Any, ...] = ()) -> Any:
    """Return the first column of the first row of a query."""
    row = conn.execute(query, params).fetchone()
    assert row is not None
    return row[0]


async def _start_trip(http: httpx.AsyncClient, raw: str, name: str = 'Tahoe weekend') -> str:
    """Start a trip as the holder of the session and return its id."""
    response = await http.post('/api/trips', json={'name': name}, headers=_cookie(raw))
    assert response.status_code == 201, response.text
    return str(response.json()['id'])


async def _invite_url(http: httpx.AsyncClient, raw: str, trip_id: str) -> str:
    """Return the organiser's invite URL."""
    response = await http.get(f'/api/trips/{trip_id}/invite', headers=_cookie(raw))
    assert response.status_code == 200, response.text
    return str(response.json()['url'])


async def test_requesting_the_invite_twice_returns_the_same_link(
    app: FastAPI, make_client: MakeClient, make_member: MakeMember, sync_conn: Conn
) -> None:
    _, raw = await make_member('Olivia Organiser')
    http = make_client(app)
    trip_id = await _start_trip(http, raw)

    first = await _invite_url(http, raw, trip_id)
    second = await _invite_url(http, raw, trip_id)

    assert first == second
    assert _scalar(sync_conn, 'SELECT count(*) FROM invites WHERE trip_id = %s', (trip_id,)) == 1


async def test_invite_url_uses_the_public_base_url(
    app: FastAPI, make_client: MakeClient, make_member: MakeMember
) -> None:
    _, raw = await make_member('Olivia Organiser')
    http = make_client(app)
    trip_id = await _start_trip(http, raw)

    url = await _invite_url(http, raw, trip_id)

    base = app.state.settings.public_base_url.rstrip('/')
    assert url.startswith(f'{base}/join/')
    assert len(_token_of(url)) == 32


async def test_a_member_who_is_not_the_organiser_cannot_read_the_invite(
    app: FastAPI, make_client: MakeClient, make_member: MakeMember
) -> None:
    _, organiser_raw = await make_member('Olivia Organiser')
    _, friend_raw = await make_member('Jo Joiner')
    http = make_client(app)
    trip_id = await _start_trip(http, organiser_raw)
    url = await _invite_url(http, organiser_raw, trip_id)
    joined = await http.post(f'/api/invites/{_token_of(url)}/join', headers=_cookie(friend_raw))
    assert joined.status_code == 200

    as_member = await http.get(f'/api/trips/{trip_id}/invite', headers=_cookie(friend_raw))
    reset_as_member = await http.post(
        f'/api/trips/{trip_id}/invite/reset', headers=_cookie(friend_raw)
    )

    assert as_member.status_code == 403
    assert reset_as_member.status_code == 403


async def test_a_stranger_cannot_read_the_invite_and_cannot_tell_the_trip_exists(
    app: FastAPI, make_client: MakeClient, make_member: MakeMember
) -> None:
    _, organiser_raw = await make_member('Olivia Organiser')
    _, stranger_raw = await make_member('Sam Stranger')
    http = make_client(app)
    trip_id = await _start_trip(http, organiser_raw)

    response = await http.get(f'/api/trips/{trip_id}/invite', headers=_cookie(stranger_raw))

    assert response.status_code == 404


async def test_reset_kills_the_old_link_and_only_the_new_one_works(
    app: FastAPI, make_client: MakeClient, make_member: MakeMember, sync_conn: Conn
) -> None:
    _, raw = await make_member('Olivia Organiser')
    http = make_client(app)
    trip_id = await _start_trip(http, raw)
    old_token = _token_of(await _invite_url(http, raw, trip_id))

    reset = await http.post(f'/api/trips/{trip_id}/invite/reset', headers=_cookie(raw))

    assert reset.status_code == 200
    new_token = _token_of(reset.json()['url'])
    assert new_token != old_token
    assert (await http.get(f'/api/invites/{old_token}')).status_code == 404
    assert (await http.get(f'/api/invites/{new_token}')).status_code == 200
    assert (await _invite_url(http, raw, trip_id)).endswith(new_token)
    active = _scalar(
        sync_conn,
        'SELECT count(*) FROM invites WHERE trip_id = %s AND revoked_at IS NULL',
        (trip_id,),
    )
    assert active == 1
    assert _scalar(sync_conn, 'SELECT count(*) FROM invites WHERE trip_id = %s', (trip_id,)) == 2


async def test_a_revoked_link_cannot_be_used_to_join(
    app: FastAPI, make_client: MakeClient, make_member: MakeMember, sync_conn: Conn
) -> None:
    _, organiser_raw = await make_member('Olivia Organiser')
    _, friend_raw = await make_member('Jo Joiner')
    http = make_client(app)
    trip_id = await _start_trip(http, organiser_raw)
    old_token = _token_of(await _invite_url(http, organiser_raw, trip_id))
    await http.post(f'/api/trips/{trip_id}/invite/reset', headers=_cookie(organiser_raw))

    response = await http.post(f'/api/invites/{old_token}/join', headers=_cookie(friend_raw))

    assert response.status_code == 404
    assert _scalar(sync_conn, 'SELECT count(*) FROM members WHERE trip_id = %s', (trip_id,)) == 1


async def test_signed_in_non_member_preview_shows_trip_organiser_and_who_is_in(
    app: FastAPI, make_client: MakeClient, make_member: MakeMember
) -> None:
    _, organiser_raw = await make_member('Olivia Organiser')
    _, friend_raw = await make_member('Jo Joiner')
    http = make_client(app)
    trip_id = await _start_trip(http, organiser_raw, 'Tahoe weekend')
    token = _token_of(await _invite_url(http, organiser_raw, trip_id))

    response = await http.get(f'/api/invites/{token}', headers=_cookie(friend_raw))

    assert response.status_code == 200
    body = response.json()
    assert body['trip_name'] == 'Tahoe weekend'
    assert body['organiser_name'] == 'Olivia Organiser'
    assert body['members'] == ['Olivia Organiser']
    assert body['joining_open'] is True
    assert body['already_member'] is False


async def test_signed_out_preview_shows_only_the_trip_name_and_organiser_first_name(
    app: FastAPI, make_client: MakeClient, make_member: MakeMember
) -> None:
    _, organiser_raw = await make_member('Olivia Organiser')
    http = make_client(app)
    trip_id = await _start_trip(http, organiser_raw, 'Tahoe weekend')
    token = _token_of(await _invite_url(http, organiser_raw, trip_id))

    response = await http.get(f'/api/invites/{token}')

    assert response.status_code == 200
    body = response.json()
    assert body['trip_name'] == 'Tahoe weekend'
    assert body['organiser_name'] == 'Olivia'
    assert body['members'] == []
    assert body['already_member'] is False
    assert 'Organiser' not in response.text


async def test_preview_of_an_unknown_token_is_404(
    app: FastAPI, make_client: MakeClient, make_member: MakeMember
) -> None:
    _, raw = await make_member('Jo Joiner')
    http = make_client(app)

    signed_out = await http.get('/api/invites/not-a-real-token')
    signed_in = await http.get('/api/invites/not-a-real-token', headers=_cookie(raw))

    assert signed_out.status_code == 404
    assert signed_in.status_code == 404


async def test_preview_for_an_existing_member_says_already_member(
    app: FastAPI, make_client: MakeClient, make_member: MakeMember
) -> None:
    _, organiser_raw = await make_member('Olivia Organiser')
    http = make_client(app)
    trip_id = await _start_trip(http, organiser_raw)
    token = _token_of(await _invite_url(http, organiser_raw, trip_id))

    response = await http.get(f'/api/invites/{token}', headers=_cookie(organiser_raw))

    assert response.status_code == 200
    assert response.json()['already_member'] is True


async def test_joining_creates_one_active_member_and_one_event(
    app: FastAPI, make_client: MakeClient, make_member: MakeMember, sync_conn: Conn
) -> None:
    friend, friend_raw = await make_member('Jo Joiner')
    _, organiser_raw = await make_member('Olivia Organiser')
    http = make_client(app)
    trip_id = await _start_trip(http, organiser_raw)
    token = _token_of(await _invite_url(http, organiser_raw, trip_id))

    response = await http.post(f'/api/invites/{token}/join', headers=_cookie(friend_raw))

    assert response.status_code == 200
    assert response.json() == {'trip_id': trip_id, 'already_member': False}
    row = sync_conn.execute(
        'SELECT role, status FROM members WHERE trip_id = %s AND account_id = %s',
        (trip_id, friend.id),
    ).fetchall()
    assert row == [('member', 'active')]
    events = sync_conn.execute(
        'SELECT type, payload FROM trip_events WHERE trip_id = %s', (trip_id,)
    ).fetchall()
    assert len(events) == 1
    assert events[0][0] == 'member.joined'
    opened = await http.get(f'/api/trips/{trip_id}', headers=_cookie(friend_raw))
    assert opened.status_code == 200
    assert [m['display_name'] for m in opened.json()['members']] == [
        'Olivia Organiser',
        'Jo Joiner',
    ]


async def test_joining_twice_leaves_exactly_one_membership_and_no_new_event(
    app: FastAPI, make_client: MakeClient, make_member: MakeMember, sync_conn: Conn
) -> None:
    friend, friend_raw = await make_member('Jo Joiner')
    _, organiser_raw = await make_member('Olivia Organiser')
    http = make_client(app)
    trip_id = await _start_trip(http, organiser_raw)
    token = _token_of(await _invite_url(http, organiser_raw, trip_id))
    await http.post(f'/api/invites/{token}/join', headers=_cookie(friend_raw))

    again = await http.post(f'/api/invites/{token}/join', headers=_cookie(friend_raw))

    assert again.status_code == 200
    assert again.json() == {'trip_id': trip_id, 'already_member': True}
    count = _scalar(
        sync_conn,
        'SELECT count(*) FROM members WHERE trip_id = %s AND account_id = %s',
        (trip_id, friend.id),
    )
    assert count == 1
    assert (
        _scalar(sync_conn, 'SELECT count(*) FROM trip_events WHERE trip_id = %s', (trip_id,)) == 1
    )


async def test_the_organiser_opening_their_own_link_is_already_a_member(
    app: FastAPI, make_client: MakeClient, make_member: MakeMember, sync_conn: Conn
) -> None:
    _, organiser_raw = await make_member('Olivia Organiser')
    http = make_client(app)
    trip_id = await _start_trip(http, organiser_raw)
    token = _token_of(await _invite_url(http, organiser_raw, trip_id))

    response = await http.post(f'/api/invites/{token}/join', headers=_cookie(organiser_raw))

    assert response.status_code == 200
    assert response.json()['already_member'] is True
    assert _scalar(sync_conn, 'SELECT count(*) FROM members WHERE trip_id = %s', (trip_id,)) == 1


async def test_joining_signed_out_is_401(
    app: FastAPI, make_client: MakeClient, make_member: MakeMember
) -> None:
    _, organiser_raw = await make_member('Olivia Organiser')
    http = make_client(app)
    trip_id = await _start_trip(http, organiser_raw)
    token = _token_of(await _invite_url(http, organiser_raw, trip_id))

    response = await http.post(f'/api/invites/{token}/join')

    assert response.status_code == 401


async def test_join_notifies_the_trip_events_channel_with_the_event_id(
    app: FastAPI, make_client: MakeClient, make_member: MakeMember, sync_conn: Conn
) -> None:
    _, friend_raw = await make_member('Jo Joiner')
    _, organiser_raw = await make_member('Olivia Organiser')
    http = make_client(app)
    trip_id = await _start_trip(http, organiser_raw)
    token = _token_of(await _invite_url(http, organiser_raw, trip_id))
    sync_conn.execute('LISTEN trip_events')

    await http.post(f'/api/invites/{token}/join', headers=_cookie(friend_raw))

    notifications = list(sync_conn.notifies(timeout=5, stop_after=1))
    event_id = _scalar(sync_conn, 'SELECT id FROM trip_events WHERE trip_id = %s', (trip_id,))
    assert [n.payload for n in notifications] == [str(event_id)]
    assert [n.channel for n in notifications] == ['trip_events']


async def test_thirteen_concurrent_joins_never_exceed_twelve_active_members(
    app: FastAPI, make_client: MakeClient, make_member: MakeMember, sync_conn: Conn
) -> None:
    _, organiser_raw = await make_member('Olivia Organiser')
    friends = [await make_member(f'Friend {index}') for index in range(13)]
    http = make_client(app)
    trip_id = await _start_trip(http, organiser_raw)
    token = _token_of(await _invite_url(http, organiser_raw, trip_id))

    responses = await asyncio.gather(
        *(http.post(f'/api/invites/{token}/join', headers=_cookie(raw)) for _, raw in friends)
    )

    statuses = sorted(response.status_code for response in responses)
    assert statuses == [200] * 11 + [409] * 2
    refused = [r.json() for r in responses if r.status_code == 409]
    assert all(body['detail'] == 'full' for body in refused)
    active = _scalar(
        sync_conn,
        "SELECT count(*) FROM members WHERE trip_id = %s AND status = 'active'",
        (trip_id,),
    )
    assert active == 12
    events = _scalar(sync_conn, 'SELECT count(*) FROM trip_events WHERE trip_id = %s', (trip_id,))
    assert events == 11


async def test_a_full_trip_refuses_the_thirteenth_person(
    app: FastAPI, make_client: MakeClient, make_member: MakeMember
) -> None:
    _, organiser_raw = await make_member('Olivia Organiser')
    http = make_client(app)
    trip_id = await _start_trip(http, organiser_raw)
    token = _token_of(await _invite_url(http, organiser_raw, trip_id))
    for index in range(11):
        _, raw = await make_member(f'Friend {index}')
        assert (
            await http.post(f'/api/invites/{token}/join', headers=_cookie(raw))
        ).status_code == 200
    _, late_raw = await make_member('Late Larry')

    response = await http.post(f'/api/invites/{token}/join', headers=_cookie(late_raw))

    assert response.status_code == 409
    assert response.json()['detail'] == 'full'


async def test_joining_closed_refuses_new_joins(
    app: FastAPI, make_client: MakeClient, make_member: MakeMember, sync_conn: Conn
) -> None:
    _, organiser_raw = await make_member('Olivia Organiser')
    _, friend_raw = await make_member('Jo Joiner')
    http = make_client(app)
    trip_id = await _start_trip(http, organiser_raw)
    token = _token_of(await _invite_url(http, organiser_raw, trip_id))
    sync_conn.execute('UPDATE trips SET joining_closed = true WHERE id = %s', (trip_id,))

    response = await http.post(f'/api/invites/{token}/join', headers=_cookie(friend_raw))
    preview = await http.get(f'/api/invites/{token}', headers=_cookie(friend_raw))

    assert response.status_code == 409
    assert response.json()['detail'] == 'closed'
    assert preview.json()['joining_open'] is False


async def test_a_member_who_left_can_rejoin_through_the_link(
    app: FastAPI, make_client: MakeClient, make_member: MakeMember, sync_conn: Conn
) -> None:
    friend, friend_raw = await make_member('Jo Joiner')
    _, organiser_raw = await make_member('Olivia Organiser')
    http = make_client(app)
    trip_id = await _start_trip(http, organiser_raw)
    token = _token_of(await _invite_url(http, organiser_raw, trip_id))
    await http.post(f'/api/invites/{token}/join', headers=_cookie(friend_raw))
    sync_conn.execute(
        "UPDATE members SET status = 'left' WHERE trip_id = %s AND account_id = %s",
        (trip_id, friend.id),
    )

    response = await http.post(f'/api/invites/{token}/join', headers=_cookie(friend_raw))

    assert response.status_code == 200
    assert response.json()['already_member'] is False
    rows = sync_conn.execute(
        'SELECT status FROM members WHERE trip_id = %s AND account_id = %s',
        (trip_id, friend.id),
    ).fetchall()
    assert rows == [('active',)]


async def test_a_removed_member_is_refused_on_the_unchanged_link_and_on_a_reset_one(
    app: FastAPI, make_client: MakeClient, make_member: MakeMember, sync_conn: Conn
) -> None:
    friend, friend_raw = await make_member('Jo Joiner')
    _, organiser_raw = await make_member('Olivia Organiser')
    http = make_client(app)
    trip_id = await _start_trip(http, organiser_raw)
    old_token = _token_of(await _invite_url(http, organiser_raw, trip_id))
    await http.post(f'/api/invites/{old_token}/join', headers=_cookie(friend_raw))
    sync_conn.execute(
        "UPDATE members SET status = 'removed' WHERE trip_id = %s AND account_id = %s",
        (trip_id, friend.id),
    )

    on_old = await http.post(f'/api/invites/{old_token}/join', headers=_cookie(friend_raw))
    reset = await http.post(f'/api/trips/{trip_id}/invite/reset', headers=_cookie(organiser_raw))
    new_token = _token_of(reset.json()['url'])
    on_new = await http.post(f'/api/invites/{new_token}/join', headers=_cookie(friend_raw))

    assert on_old.status_code == 409
    assert on_old.json()['detail'] == 'removed'
    assert on_new.status_code == 409
    assert on_new.json()['detail'] == 'removed'
    status = _scalar(
        sync_conn,
        'SELECT status FROM members WHERE trip_id = %s AND account_id = %s',
        (trip_id, friend.id),
    )
    assert status == 'removed'


async def test_the_invites_table_stores_only_the_sha256_of_the_token(
    app: FastAPI, make_client: MakeClient, make_member: MakeMember, sync_conn: Conn
) -> None:
    _, organiser_raw = await make_member('Olivia Organiser')
    http = make_client(app)
    trip_id = await _start_trip(http, organiser_raw)
    token = _token_of(await _invite_url(http, organiser_raw, trip_id))

    rows = sync_conn.execute('SELECT * FROM invites WHERE trip_id = %s', (trip_id,)).fetchall()

    assert len(rows) == 1
    for value in rows[0]:
        assert value != token
        assert value != token.encode()
        assert token not in str(value)
    digests = [bytes(value) for value in rows[0] if isinstance(value, bytes | memoryview)]
    assert digests == [hashlib.sha256(token.encode()).digest()]


async def test_the_eleventh_invite_request_in_a_minute_answers_429(
    make_app: MakeApp, make_client: MakeClient, make_member: MakeMember
) -> None:
    limited_app = make_app(False)
    _, organiser_raw = await make_member('Olivia Organiser')
    http = make_client(limited_app)
    trip_id = await _start_trip(http, organiser_raw)
    token = _token_of(await _invite_url(http, organiser_raw, trip_id))

    statuses = [(await http.get(f'/api/invites/{token}')).status_code for _ in range(11)]

    assert statuses == [200] * 10 + [429]
    blocked = await http.get(f'/api/invites/{token}')
    assert blocked.status_code == 429
    assert int(blocked.headers['Retry-After']) >= 1
    joined = await http.post(f'/api/invites/{token}/join', headers=_cookie(organiser_raw))
    assert joined.status_code == 429


async def test_a_persona_cannot_join_a_non_demo_trip(
    app: FastAPI,
    make_client: MakeClient,
    make_member: MakeMember,
    persona_client: PersonaClient,
    sync_conn: Conn,
) -> None:
    _, organiser_raw = await make_member('Olivia Organiser')
    http = make_client(app)
    trip_id = await _start_trip(http, organiser_raw)
    token = _token_of(await _invite_url(http, organiser_raw, trip_id))
    persona = await persona_client('sam')

    preview = await persona.get(f'/api/invites/{token}')
    join = await persona.post(f'/api/invites/{token}/join')

    assert preview.status_code == 200
    assert preview.json()['members'] == []
    assert join.status_code == 404
    assert _scalar(sync_conn, 'SELECT count(*) FROM members WHERE trip_id = %s', (trip_id,)) == 1


async def test_a_persona_joins_a_persona_trip_with_the_link(
    persona_client: PersonaClient, sync_conn: Conn
) -> None:
    maya = await persona_client('maya')
    sam = await persona_client('sam')
    created = await maya.post('/api/trips', json={'name': 'Demo trip'})
    trip_id = created.json()['id']
    url = (await maya.get(f'/api/trips/{trip_id}/invite')).json()['url']

    joined = await sam.post(f'/api/invites/{_token_of(url)}/join')

    assert joined.status_code == 200
    assert joined.json() == {'trip_id': trip_id, 'already_member': False}
    assert _scalar(sync_conn, 'SELECT count(*) FROM members WHERE trip_id = %s', (trip_id,)) == 2

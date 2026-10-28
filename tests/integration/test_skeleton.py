"""Walking-skeleton trip API (D-20): a signed-in account starts a trip and opens it."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import psycopg
import pytest

if TYPE_CHECKING:
    from conftest import MakeApp, MakeClient, MakeMember, PersonaClient


Conn = psycopg.Connection[tuple[object, ...]]


def _cookie(raw: str) -> dict[str, str]:
    """Return a Cookie header carrying the raw session value."""
    return {'Cookie': f'tp_session={raw}'}


async def test_persona_starts_a_trip_and_reads_it_back(
    persona_client: PersonaClient, sync_conn: Conn
) -> None:
    http = await persona_client('maya')

    created = await http.post('/api/trips', json={'name': 'Tahoe weekend'})

    assert created.status_code == 201
    body = created.json()
    assert body['name'] == 'Tahoe weekend'
    trip_id = body['id']

    opened = await http.get(f'/api/trips/{trip_id}')

    assert opened.status_code == 200
    view = opened.json()
    assert view['id'] == trip_id
    assert view['name'] == 'Tahoe weekend'
    assert view['is_organiser'] is True
    assert len(view['members']) == 1
    member = view['members'][0]
    assert member['display_name'] == 'Maya'
    assert member['role'] == 'organiser'
    assert uuid.UUID(member['account_id'])

    trips = sync_conn.execute(
        'SELECT name, organiser_account_id FROM trips WHERE id = %s', (trip_id,)
    ).fetchall()
    assert len(trips) == 1
    members = sync_conn.execute(
        'SELECT account_id, role, status FROM members WHERE trip_id = %s', (trip_id,)
    ).fetchall()
    assert len(members) == 1
    assert str(members[0][0]) == member['account_id']
    assert (members[0][1], members[0][2]) == ('organiser', 'active')
    assert members[0][0] == trips[0][1]


async def test_persona_trip_is_a_demo_trip(persona_client: PersonaClient, sync_conn: Conn) -> None:
    http = await persona_client('maya')

    created = await http.post('/api/trips', json={'name': 'Demo trip'})

    row = sync_conn.execute(
        'SELECT demo_mode FROM trips WHERE id = %s', (created.json()['id'],)
    ).fetchone()
    assert row is not None
    assert row[0] is True


async def test_member_trip_is_not_a_demo_trip(
    make_app: MakeApp, make_client: MakeClient, make_member: MakeMember, sync_conn: Conn
) -> None:
    _, raw = await make_member('Real Person')
    http = make_client(make_app(False))

    created = await http.post('/api/trips', json={'name': 'Real trip'}, headers=_cookie(raw))

    assert created.status_code == 201
    row = sync_conn.execute(
        'SELECT demo_mode FROM trips WHERE id = %s', (created.json()['id'],)
    ).fetchone()
    assert row is not None
    assert row[0] is False


async def test_non_member_gets_404_for_someone_elses_trip(
    make_app: MakeApp, make_client: MakeClient, make_member: MakeMember
) -> None:
    _, organiser_raw = await make_member('Organiser')
    _, stranger_raw = await make_member('Stranger')
    http = make_client(make_app(False))
    created = await http.post(
        '/api/trips', json={'name': 'Private'}, headers=_cookie(organiser_raw)
    )
    trip_id = created.json()['id']

    stranger = await http.get(f'/api/trips/{trip_id}', headers=_cookie(stranger_raw))
    unknown = await http.get(f'/api/trips/{uuid.uuid4()}', headers=_cookie(stranger_raw))

    assert stranger.status_code == 404
    assert unknown.status_code == 404
    assert stranger.json() == unknown.json()


async def test_signed_out_requests_get_401(make_app: MakeApp, make_client: MakeClient) -> None:
    http = make_client(make_app(False))

    created = await http.post('/api/trips', json={'name': 'Nope'})
    opened = await http.get(f'/api/trips/{uuid.uuid4()}')

    assert created.status_code == 401
    assert opened.status_code == 401


@pytest.mark.parametrize('name', ['', 'x' * 81])
async def test_trip_name_must_be_1_to_80_characters(
    persona_client: PersonaClient, name: str, sync_conn: Conn
) -> None:
    http = await persona_client('maya')

    response = await http.post('/api/trips', json={'name': name})

    assert response.status_code == 422
    row = sync_conn.execute('SELECT count(*) FROM trips').fetchone()
    assert row is not None
    assert row[0] == 0


async def test_trip_name_of_exactly_80_characters_is_accepted(
    persona_client: PersonaClient,
) -> None:
    http = await persona_client('maya')

    response = await http.post('/api/trips', json={'name': 'x' * 80})

    assert response.status_code == 201

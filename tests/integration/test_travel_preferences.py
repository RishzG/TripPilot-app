"""Persistence and privacy boundaries for the first group-workspace slice."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import httpx
import psycopg
import pytest

from trippilot.trips.models import Member

if TYPE_CHECKING:
    from conftest import MakeMember, PersonaClient
    from sqlalchemy.ext.asyncio import AsyncSession

Conn = psycopg.Connection[tuple[object, ...]]


async def group(
    client: httpx.AsyncClient, make_member: MakeMember, db: AsyncSession
) -> tuple[str, dict[str, str], dict[str, str], dict[str, str]]:
    """Create a trip and two active members, plus a signed-in outsider."""
    _, leader = await make_member('Leader')
    friend, friend_raw = await make_member('Friend')
    _, outsider = await make_member('Outsider')
    leader_headers = {'Cookie': f'tp_session={leader}'}
    created = await client.post(
        '/api/trips', json={'name': 'Chicago weekend'}, headers=leader_headers
    )
    assert created.status_code == 201, created.text
    trip_id = created.json()['id']
    db.add(Member(trip_id=uuid.UUID(trip_id), account_id=friend.id, role='member'))
    await db.commit()
    return (
        trip_id,
        leader_headers,
        {'Cookie': f'tp_session={friend_raw}'},
        {'Cookie': f'tp_session={outsider}'},
    )


async def test_roundtrip_and_private_projection(
    client: httpx.AsyncClient, make_member: MakeMember, db: AsyncSession, sync_conn: Conn
) -> None:
    trip_id, leader, friend, _ = await group(client, make_member, db)
    path = f'/api/trips/{trip_id}/preferences'
    private = {
        'origin': '  Chicago, IL  ',
        'interests': 'Museums and hiking',
        'pace': 'relaxed',
        'budget_cents': 42137,
        'dietary_notes': 'Private allergy details',
    }
    saved = await client.put(f'{path}/me', json=private, headers=friend)
    assert saved.status_code == 200, saved.text
    assert saved.json()['mine'] == {**private, 'origin': 'Chicago, IL'}
    saved_friend = next(m for m in saved.json()['members'] if m['display_name'] == 'Friend')
    assert saved_friend['origin'] == 'Chicago, IL'
    assert saved_friend['interests'] == private['interests']
    assert saved_friend['pace'] == private['pace']
    assert 'budget_cents' not in saved_friend and 'dietary_notes' not in saved_friend
    own = (await client.get(path, headers=friend)).json()
    assert own['mine'] == {**private, 'origin': 'Chicago, IL'}
    other = await client.get(path, headers=leader)
    assert other.status_code == 200
    assert other.json()['mine']['budget_cents'] is None
    assert other.json()['mine']['dietary_notes'] == ''
    public = next(
        member for member in other.json()['members'] if member['display_name'] == 'Friend'
    )
    assert public['origin'] == 'Chicago, IL'
    assert public['pace'] == 'relaxed'
    assert 'budget_cents' not in public and 'dietary_notes' not in public
    assert 'Private allergy details' not in other.text and '42137' not in other.text
    trip = await client.get(f'/api/trips/{trip_id}', headers=leader)
    assert 'Private allergy details' not in trip.text and '42137' not in trip.text
    events = sync_conn.execute(
        "SELECT payload FROM trip_events WHERE trip_id = %s AND type = 'preferences.updated'",
        (trip_id,),
    ).fetchall()
    assert events == [({},)]


async def test_replace_clear_and_trip_isolation(
    client: httpx.AsyncClient, make_member: MakeMember, db: AsyncSession, sync_conn: Conn
) -> None:
    trip_id, leader, _, _ = await group(client, make_member, db)
    path = f'/api/trips/{trip_id}/preferences'
    for amount in (0, 12345):
        response = await client.put(f'{path}/me', json={'budget_cents': amount}, headers=leader)
        assert response.status_code == 200, response.text
        assert (await client.get(path, headers=leader)).json()['mine']['budget_cents'] == amount
    assert sync_conn.execute(
        'SELECT count(*) FROM travel_profiles WHERE trip_id = %s', (trip_id,)
    ).fetchone() == (1,)
    second = await client.post('/api/trips', json={'name': 'Another trip'}, headers=leader)
    second_path = f'/api/trips/{second.json()["id"]}/preferences'
    assert (await client.get(second_path, headers=leader)).json()['mine']['budget_cents'] is None
    cleared = await client.put(f'{path}/me', json={}, headers=leader)
    assert cleared.status_code == 200
    assert cleared.json()['mine']['budget_cents'] is None


async def test_membership_and_owner_boundaries(
    client: httpx.AsyncClient, make_member: MakeMember, db: AsyncSession
) -> None:
    trip_id, leader, friend, outsider = await group(client, make_member, db)
    path = f'/api/trips/{trip_id}/preferences'
    for headers, expected in (({}, 401), (outsider, 404)):
        assert (await client.get(path, headers=headers)).status_code == expected
        assert (await client.put(f'{path}/me', json={}, headers=headers)).status_code == expected
    spoofed = await client.put(f'{path}/me', json={'account_id': str(uuid.uuid4())}, headers=friend)
    assert spoofed.status_code == 422
    own = (await client.get(f'/api/trips/{trip_id}', headers=friend)).json()
    friend_id = next(m['account_id'] for m in own['members'] if m['role'] == 'member')
    removed = await client.post(f'/api/trips/{trip_id}/members/{friend_id}/remove', headers=leader)
    assert removed.status_code == 200
    assert (await client.get(path, headers=friend)).status_code == 404
    assert (await client.put(f'{path}/me', json={}, headers=friend)).status_code == 404
    assert len((await client.get(path, headers=leader)).json()['members']) == 1


@pytest.mark.parametrize(
    'body',
    [
        {'budget_cents': -1},
        {'budget_cents': 100_000_001},
        {'budget_cents': 1.5},
        {'budget_cents': True},
        {'budget_cents': '1250'},
        {'pace': 'rushed'},
        {'origin': 'a' * 161},
        {'interests': 'a' * 1001},
        {'dietary_notes': 'a' * 1001},
    ],
)
async def test_invalid_input_cannot_mutate_saved_preferences(
    client: httpx.AsyncClient, make_member: MakeMember, db: AsyncSession, body: dict[str, object]
) -> None:
    trip_id, leader, _, _ = await group(client, make_member, db)
    path = f'/api/trips/{trip_id}/preferences'
    await client.put(f'{path}/me', json={'origin': 'Boston'}, headers=leader)
    rejected = await client.put(f'{path}/me', json=body, headers=leader)
    assert rejected.status_code == 422
    assert (await client.get(path, headers=leader)).json()['mine']['origin'] == 'Boston'


async def test_persona_preferences_are_scoped_to_the_demo_trip(
    persona_client: PersonaClient,
) -> None:
    maya = await persona_client('maya')
    first = await maya.post('/api/trips', json={'name': 'Demo one'})
    second = await maya.post('/api/trips', json={'name': 'Demo two'})
    path = f'/api/trips/{first.json()["id"]}/preferences'
    assert (await maya.put(f'{path}/me', json={'origin': 'Denver'})).status_code == 200
    second_path = f'/api/trips/{second.json()["id"]}/preferences'
    assert (await maya.get(second_path)).json()['mine']['origin'] == ''


async def test_csrf_refuses_cross_origin_write(
    client: httpx.AsyncClient, make_member: MakeMember, db: AsyncSession
) -> None:
    trip_id, leader, _, _ = await group(client, make_member, db)
    response = await client.put(
        f'/api/trips/{trip_id}/preferences/me',
        json={'origin': 'Boston'},
        headers={**leader, 'Origin': 'https://unrelated.example'},
    )
    assert response.status_code == 403

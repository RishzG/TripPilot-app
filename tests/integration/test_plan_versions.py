"""Versioned draft access, historical splits and retry safety."""

from __future__ import annotations

import asyncio
import uuid
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    import httpx
    from conftest import PersonaClient


@pytest.fixture
async def group(
    persona_client: PersonaClient,
) -> tuple[httpx.AsyncClient, httpx.AsyncClient, str, list[str]]:
    leader = await persona_client('maya')
    member = await persona_client('sam')
    trip = await leader.post('/api/trips', json={'name': 'Itinerary test'})
    assert trip.status_code == 201
    path = f'/api/trips/{trip.json()["id"]}'
    token = (await leader.get(f'{path}/invite')).json()['url'].rsplit('/', 1)[1]
    assert (await member.post(f'/api/invites/{token}/join')).status_code == 200
    ids = [(await client.get('/api/me')).json()['id'] for client in (leader, member)]
    return leader, member, path, ids


async def test_history_and_estimated_cents(
    group: tuple[httpx.AsyncClient, httpx.AsyncClient, str, list[str]],
    persona_client: PersonaClient,
) -> None:
    leader, member, path, ids = group
    route = f'{path}/plans'
    outsider = await persona_client('ana')
    assert (await member.get(route)).json() == {'draft': None}
    item = {
        'id': str(uuid.uuid4()),
        'title': 'Museum',
        'location': 'Old town',
        'day': '2026-12-01',
        'estimated_cents': 101,
        'participant_ids': sorted(ids, reverse=True),
    }
    unpriced = {**item, 'id': str(uuid.uuid4()), 'title': 'Dinner', 'estimated_cents': None}
    first = {'request_id': str(uuid.uuid4()), 'base_version': 0, 'items': [item, unpriced]}
    assert (await member.post(route, json=first)).status_code == 403
    assert (await outsider.post(route, json=first)).status_code == 404
    assert (await outsider.get(route)).status_code == 404

    # Concurrent retries with the same request ID write exactly one version.
    responses = await asyncio.gather(*(leader.post(route, json=first) for _ in range(3)))
    assert all(response.status_code == 201 for response in responses)
    saved = responses[0].json()
    assert all(response.json() == saved for response in responses)
    assert saved['version'] == 1
    assert saved['currency'] == 'USD'
    assert saved['estimated_total_cents'] == 101
    assert saved['unpriced_items'] == 1
    assert [share['cents'] for share in saved['items'][0]['shares']] == [51, 50]
    assert [share['account_id'] for share in saved['items'][0]['shares']] == sorted(ids)
    assert [share['cents'] for share in saved['items'][1]['shares']] == [None, None]
    assert sum(share['cents'] for share in saved['member_totals']) == 101

    second = {
        'request_id': str(uuid.uuid4()),
        'base_version': 1,
        'items': [{**item, 'estimated_cents': 0, 'participant_ids': ids[:1]}],
    }
    revised = await leader.post(route, json=second)
    assert revised.status_code == 201, revised.text
    assert revised.json()['items'][0]['shares'][0]['cents'] == 0
    assert (await member.get(route)).json()['draft']['version'] == 2
    assert (await member.get(route, params={'version': 1})).json()['draft'] == saved
    assert (await member.get(route, params={'version': 3})).status_code == 404

    # Reject a competing edit from the previous base, and reject reusing an ID with new content.
    assert (
        await leader.post(route, json={**second, 'request_id': str(uuid.uuid4())})
    ).status_code == 409
    assert (await leader.post(route, json={**second, 'items': []})).status_code == 409
    assert (await leader.post(route, json=first)).json() == saved

    removed = await leader.post(f'{path}/members/{ids[1]}/remove')
    assert removed.status_code == 200
    assert (await member.get(route, params={'version': 1})).status_code == 404
    assert (await leader.get(route, params={'version': 1})).json()['draft'] == saved
    after_removal = {**first, 'request_id': str(uuid.uuid4()), 'base_version': 2}
    assert (await leader.post(route, json=after_removal)).status_code == 422


@pytest.mark.parametrize(
    'change',
    [
        {'estimated_cents': 1.5},
        {'estimated_cents': -1},
        {'estimated_cents': '100'},
        {'participant_ids': []},
        {'day': '2026-02-30'},
    ],
)
async def test_invalid_items_do_not_create_versions(
    group: tuple[httpx.AsyncClient, httpx.AsyncClient, str, list[str]],
    change: dict[str, object],
) -> None:
    leader, _, path, ids = group
    item = {
        'id': str(uuid.uuid4()),
        'title': 'Museum',
        'location': '',
        'day': '2026-12-01',
        'estimated_cents': 100,
        'participant_ids': ids,
        **change,
    }
    route = f'{path}/plans'
    body = {'request_id': str(uuid.uuid4()), 'base_version': 0, 'items': [item]}
    assert (await leader.post(route, json=body)).status_code == 422
    assert (await leader.get(route)).json() == {'draft': None}

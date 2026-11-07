"""Pilot request authorization, durable dispatch, source history and stale-run safety."""

from __future__ import annotations

import asyncio
import uuid
from typing import TYPE_CHECKING

import pytest

from trippilot.trips.pilot import create_pilot_draft

if TYPE_CHECKING:
    import httpx
    from conftest import PersonaClient

CONTEXT = {
    'destination': 'London',
    'start_date': '2026-12-01',
    'end_date': '2026-12-02',
    'timezone': 'Europe/London',
}


@pytest.fixture
async def group(
    persona_client: PersonaClient,
) -> tuple[httpx.AsyncClient, httpx.AsyncClient, str, str]:
    leader = await persona_client('maya')
    member = await persona_client('sam')
    created = await leader.post('/api/trips', json={'name': 'Pilot preview'})
    trip_id = created.json()['id']
    path = f'/api/trips/{trip_id}'
    token = (await leader.get(f'{path}/invite')).json()['url'].rsplit('/', 1)[1]
    assert (await member.post(f'/api/invites/{token}/join')).status_code == 200
    return leader, member, path, trip_id


async def test_pilot_queues_once_and_uses_public_chat(
    group: tuple[httpx.AsyncClient, httpx.AsyncClient, str, str],
) -> None:
    leader, member, path, trip_id = group
    request = {'request_id': str(uuid.uuid4())}
    route = f'{path}/pilot'
    assert (await leader.post(route, json=request)).status_code == 409
    assert (await member.put(f'{path}/planning-context', json=CONTEXT)).status_code == 403
    assert (await leader.put(f'{path}/planning-context', json=CONTEXT)).status_code == 200
    assert (await member.get(path)).json()['planning_context'] == CONTEXT
    assert (await member.post(route, json=request)).status_code == 403
    assert (
        await member.post(
            f'{path}/concerns',
            json={
                'content': 'dinosaurs fossils science wildlife',
                'client_concern_id': str(uuid.uuid4()),
            },
        )
    ).status_code == 201
    assert (
        await member.post(
            f'{path}/messages',
            json={
                'content': 'art, fashion and design, then a park walk',
                'client_message_id': str(uuid.uuid4()),
            },
        )
    ).status_code == 201

    replies = await asyncio.gather(*(leader.post(route, json=request) for _ in range(3)))
    assert all(reply.status_code == 202 for reply in replies), [reply.text for reply in replies]
    queued = replies[0].json()
    assert queued['state'] == 'queued'
    assert all(reply.json() == queued for reply in replies)
    assert (await leader.post(route, json={'request_id': str(uuid.uuid4())})).status_code == 409

    await create_pilot_draft(run_id=queued['id'], trip_id=trip_id)
    await create_pilot_draft(run_id=queued['id'], trip_id=trip_id)
    assert (await member.get(route)).json()['run']['state'] == 'ready'
    draft = (await member.get(f'{path}/plans')).json()['draft']
    assert draft['version'] == 1
    assert [item['title'] for item in draft['items']] == [
        'V&A South Kensington',
        'Hyde Park lakeside walk',
    ]
    assert [item['day'] for item in draft['items']] == ['2026-12-01', '2026-12-02']
    assert draft['items'][0]['source']['url'] == 'https://www.vam.ac.uk/south-kensington'
    assert draft['items'][0]['shares'][0]['cents'] == 0
    assert draft['items'][1]['shares'][0]['cents'] is None
    assert draft['unpriced_items'] == 1

    editable = [
        {key: value for key, value in item.items() if key not in {'shares', 'source'}}
        for item in draft['items']
    ]
    editable[1]['estimated_cents'] = 800
    revision = await leader.post(
        f'{path}/plans',
        json={
            'request_id': str(uuid.uuid4()),
            'base_version': 1,
            'items': editable,
        },
    )
    assert revision.status_code == 201, revision.text
    assert revision.json()['items'][0]['source'] == draft['items'][0]['source']
    assert revision.json()['items'][1]['source'] is None
    assert (await member.get(f'{path}/plans?version=1')).json()['draft'] == draft


async def test_stale_context_fails_without_creating_draft(
    group: tuple[httpx.AsyncClient, httpx.AsyncClient, str, str],
) -> None:
    leader, _, path, trip_id = group
    assert (await leader.put(f'{path}/planning-context', json=CONTEXT)).status_code == 200
    request = await leader.post(f'{path}/pilot', json={'request_id': str(uuid.uuid4())})
    assert request.status_code == 202, request.text
    assert (
        await leader.put(
            f'{path}/planning-context',
            json={**CONTEXT, 'end_date': '2026-12-03'},
        )
    ).status_code == 200
    await create_pilot_draft(run_id=request.json()['id'], trip_id=trip_id)
    run = (await leader.get(f'{path}/pilot')).json()['run']
    assert run['state'] == 'failed'
    assert 'Trip details changed' in run['message']
    assert (await leader.get(f'{path}/plans')).json() == {'draft': None}

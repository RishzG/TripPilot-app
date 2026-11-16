"""A replacement recalculates cents, resets consent, and applies exactly once."""

from __future__ import annotations

import asyncio
import uuid
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from conftest import PersonaClient


async def test_one_activity_replacement_with_opt_out_and_fresh_acceptance(
    persona_client: PersonaClient,
) -> None:
    maya = await persona_client('maya')
    sam = await persona_client('sam')
    ana = await persona_client('ana')
    created = await maya.post('/api/trips', json={'name': 'London replanning'})
    trip = f'/api/trips/{created.json()["id"]}'
    root = f'{trip}/replanning'
    token = (await maya.get(f'{trip}/invite')).json()['url'].rsplit('/', 1)[1]
    for friend in (sam, ana):
        assert (await friend.post(f'/api/invites/{token}/join')).status_code == 200
    ids = [(await client.get('/api/me')).json()['id'] for client in (maya, sam, ana)]
    item = {
        'id': str(uuid.uuid4()),
        'title': 'Museum visit',
        'day': '2026-12-01',
        'location': 'South Kensington',
        'estimated_cents': 0,
        'participant_ids': ids,
    }
    other = {
        **item,
        'id': str(uuid.uuid4()),
        'title': 'Dinner',
        'day': '2026-12-02',
        'estimated_cents': 1201,
    }
    initial = await maya.post(
        f'{trip}/plans',
        json={'request_id': str(uuid.uuid4()), 'base_version': 0, 'items': [item, other]},
    )
    assert initial.status_code == 201, initial.text
    v1 = initial.json()
    assert (await sam.put(f'{root}/current', json={'version': 1})).status_code == 403
    assert (await maya.put(f'{root}/current', json={'version': 1})).status_code == 200
    assert (await sam.get(trip)).json()['current_plan_version'] == 1

    replacement = {**item, 'title': 'Guided tour', 'estimated_cents': 10001}
    body = {'proposal_id': str(uuid.uuid4()), 'base_version': 1, 'replacement': replacement}
    assert (await sam.post(f'{root}/proposals', json=body)).status_code == 403
    proposed = await maya.post(f'{root}/proposals', json=body)
    assert proposed.status_code == 201, proposed.text
    v1_proposal = proposed.json()
    assert v1_proposal['revision'] == 1
    assert v1_proposal['original'] == v1['items'][0]
    assert sum(share['cents'] for share in v1_proposal['replacement']['shares']) == 10001
    assert (await maya.post(f'{root}/proposals', json=body)).json() == v1_proposal
    assert (
        await maya.post(f'{root}/proposals', json={**body, 'proposal_id': str(uuid.uuid4())})
    ).status_code == 409
    response = f'{root}/proposals/{body["proposal_id"]}/respond'
    accept1 = {'revision': 1, 'action': 'accept'}
    assert (await maya.post(response, json=accept1)).json()['accepted_ids'] == [ids[0]]
    assert (await maya.get(trip)).json()['current_plan_version'] == 1

    opted_out = await sam.post(response, json={'revision': 1, 'action': 'opt_out'})
    assert opted_out.status_code == 200, opted_out.text
    v2_proposal = opted_out.json()
    assert v2_proposal['revision'] == 2
    assert v2_proposal['accepted_ids'] == []
    assert set(v2_proposal['affected_ids']) == {ids[0], ids[2]}
    assert v2_proposal['opted_out_ids'] == [ids[1]]
    assert [share['cents'] for share in v2_proposal['replacement']['shares']] == [5001, 5000]
    assert (await ana.post(response, json=accept1)).status_code == 409
    accept2 = {'revision': 2, 'action': 'accept'}
    assert (await sam.post(response, json=accept2)).status_code == 403
    assert (
        await sam.post(response, json={'revision': 1, 'action': 'opt_out'})
    ).json() == v2_proposal

    # A new, unrelated draft does not become current or get overwritten by approval.
    parallel = await maya.post(
        f'{trip}/plans',
        json={'request_id': str(uuid.uuid4()), 'base_version': 1, 'items': [other]},
    )
    assert parallel.status_code == 201
    assert (await maya.put(f'{root}/current', json={'version': 2})).status_code == 409

    responses = await asyncio.gather(
        maya.post(response, json=accept2),
        ana.post(response, json=accept2),
    )
    assert all(reply.status_code == 200 for reply in responses)
    final = (await ana.get(root)).json()['proposal']
    assert final['state'] == 'applied'
    assert final['applied_version'] == 3
    assert (await maya.post(response, json=accept2)).json() == final
    assert (await sam.get(trip)).json()['current_plan_version'] == 3
    assert (await sam.get(f'{trip}/plans?version=1')).json()['draft'] == v1
    assert (await sam.get(f'{trip}/plans?version=2')).json()['draft'] == parallel.json()
    applied = (await sam.get(f'{trip}/plans')).json()['draft']
    assert applied['version'] == 3
    assert applied['items'] == [v2_proposal['replacement'], v1['items'][1]]
    assert applied['estimated_total_cents'] == 11202
    assert sum(share['cents'] for share in applied['member_totals']) == 11202

    for friend in (sam, ana):
        assert (await friend.post(f'{trip}/leave')).status_code == 200
    assert (await maya.delete(trip)).status_code == 200


async def test_last_participant_opt_out_closes_proposal_and_keeps_current_plan(
    persona_client: PersonaClient,
) -> None:
    maya = await persona_client('maya')
    created = await maya.post('/api/trips', json={'name': 'Solo replacement'})
    trip = f'/api/trips/{created.json()["id"]}'
    root = f'{trip}/replanning'
    item = {
        'id': str(uuid.uuid4()),
        'title': 'Museum',
        'day': '2026-12-01',
        'location': '',
        'estimated_cents': 0,
        'participant_ids': [(await maya.get('/api/me')).json()['id']],
    }
    initial = await maya.post(
        f'{trip}/plans',
        json={'request_id': str(uuid.uuid4()), 'base_version': 0, 'items': [item]},
    )
    assert initial.status_code == 201
    assert (await maya.put(f'{root}/current', json={'version': 1})).status_code == 200
    proposal_id = str(uuid.uuid4())
    body = {
        'proposal_id': proposal_id,
        'base_version': 1,
        'replacement': {**item, 'title': 'Tour', 'estimated_cents': 2000},
    }
    assert (await maya.post(f'{root}/proposals', json=body)).status_code == 201
    response = f'{root}/proposals/{proposal_id}/respond'
    choice = {'revision': 1, 'action': 'opt_out'}
    closed = await maya.post(response, json=choice)
    assert closed.status_code == 200, closed.text
    assert closed.json()['state'] == 'withdrawn'
    assert closed.json()['opted_out_ids'] == item['participant_ids']
    assert closed.json()['affected_ids'] == []
    assert (await maya.post(response, json=choice)).json() == closed.json()
    assert (await maya.get(trip)).json()['current_plan_version'] == 1
    assert (await maya.get(f'{trip}/plans')).json()['draft'] == initial.json()
    assert (
        await maya.post(f'{root}/proposals', json={**body, 'proposal_id': str(uuid.uuid4())})
    ).status_code == 201

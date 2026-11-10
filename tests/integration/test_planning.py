"""Plan ownership, immutable revisions, private inputs, stale decisions and durable runs."""

from __future__ import annotations

import json
import uuid
from datetime import date
from typing import TYPE_CHECKING, Any

import pytest
from pydantic import SecretStr

from trippilot.planning.domain import Draft
from trippilot.planning.sample import sample_plan
from trippilot.settings import Settings

if TYPE_CHECKING:
    import httpx
    import psycopg
    from conftest import MakeApp, MakeClient, PersonaClient


async def group(persona_client: PersonaClient) -> tuple[httpx.AsyncClient, httpx.AsyncClient, str]:
    leader = await persona_client('maya')
    member = await persona_client('sam')
    created = (await leader.post('/api/trips', json={'name': 'Plan trip'})).json()
    path = f'/api/trips/{created["id"]}'
    token = (await leader.get(f'{path}/invite')).json()['url'].rsplit('/', 1)[1]
    assert (await member.post(f'/api/invites/{token}/join')).status_code == 200
    return leader, member, path


async def test_context_access_revision_and_timezone(persona_client: PersonaClient) -> None:
    leader, member, path = await group(persona_client)
    outsider = await persona_client('ana')
    endpoint = f'{path}/planning'
    assert (await outsider.get(endpoint)).status_code == 404
    context = (await leader.get(endpoint)).json()['context']
    context.update(
        destination='Chicago',
        start_date='2026-11-07',
        end_date='2026-11-08',
        timezone='America/Chicago',
    )
    assert (await member.put(f'{endpoint}/context', json=context)).status_code == 403
    saved = await leader.put(f'{endpoint}/context', json=context)
    assert saved.status_code == 200, saved.text
    assert saved.json()['revision'] == 1
    assert (await leader.put(f'{endpoint}/context', json=context)).status_code == 409
    bad = {**saved.json(), 'timezone': 'Bad/Zone'}
    assert (await leader.put(f'{endpoint}/context', json=bad)).status_code == 422
    assert (await member.get(endpoint)).json()['context'] == saved.json()


async def test_cancel_preserves_history_and_requires_every_affected_response(
    persona_client: PersonaClient, sync_conn: psycopg.Connection
) -> None:
    leader, member, path = await group(persona_client)
    endpoint = f'{path}/planning'
    versions = (await leader.post(f'{endpoint}/sample')).json()
    base, candidate = versions
    assert (await leader.post(f'{endpoint}/sample')).status_code == 409
    assert sum(base['totals'].values()) == base['total_cents']
    assert (await member.post(f'{endpoint}/versions/{base["id"]}/select')).status_code == 403
    assert (await leader.post(f'{endpoint}/versions/{base["id"]}/select')).status_code == 200
    body = {
        'base_id': base['id'],
        'cancelled_item_id': base['items'][1]['id'],
        'candidate_version_id': candidate['id'],
        'candidate_item_id': candidate['items'][1]['id'],
    }
    created = await leader.post(f'{endpoint}/proposals', json=body)
    assert created.status_code == 201, created.text
    proposal = created.json()
    state = (await member.get(endpoint)).json()
    revision = next(v for v in state['versions'] if v['id'] == proposal['version_id'])
    assert revision['items'][0] == base['items'][0]
    assert revision['items'][1] == candidate['items'][1]
    assert all(delta == -3200 for delta in proposal['cost_differences'].values())
    route = f'{endpoint}/proposals/{proposal["id"]}'
    assert (await leader.post(f'{route}/finalize')).status_code == 409
    assert (await leader.post(f'{endpoint}/versions/{revision["id"]}/select')).status_code == 409
    response = {'version_id': proposal['version_id'], 'response': 'accept'}
    assert (await leader.post(f'{route}/respond', json=response)).status_code == 200
    assert (
        await member.post(f'{route}/respond', json={**response, 'response': 'discuss'})
    ).status_code == 200
    assert (await leader.post(f'{route}/finalize')).status_code == 409
    assert (await member.post(f'{route}/respond', json=response)).status_code == 200
    assert (await member.post(f'{route}/finalize')).status_code == 403
    assert (await leader.post(f'{route}/finalize')).status_code == 200
    after = (await member.get(endpoint)).json()
    assert after['selected_id'] == proposal['version_id']
    assert next(v for v in after['versions'] if v['id'] == base['id']) == base
    with pytest.raises(Exception, match='immutable'):
        sync_conn.execute('UPDATE plan_versions SET title=%s WHERE id=%s', ('changed', base['id']))


async def test_private_inputs_invalidate_decisions_without_becoming_public(
    persona_client: PersonaClient,
) -> None:
    leader, member, path = await group(persona_client)
    endpoint = f'{path}/planning'
    versions = (await leader.post(f'{endpoint}/sample')).json()
    secret = 'private medical concern marker'
    await member.post(
        f'{path}/concerns', json={'content': secret, 'client_concern_id': str(uuid.uuid4())}
    )
    state = await leader.get(endpoint)
    assert secret not in state.text
    assert all(not version['current'] for version in state.json()['versions'])
    assert (await leader.post(f'{endpoint}/versions/{versions[0]["id"]}/select')).status_code == 409


async def test_worker_uses_private_inputs_but_projects_notes_only_to_owner(
    make_app: MakeApp,
    make_client: MakeClient,
    monkeypatch: pytest.MonkeyPatch,
    sync_conn: psycopg.Connection,
) -> None:
    from trippilot.planning import tasks
    from trippilot.settings import get_settings

    monkeypatch.setattr(get_settings(), 'ai_gateway_api_key', SecretStr('test-key'))
    monkeypatch.setattr(get_settings(), 'pilot_model', 'test/model')
    app = make_app(True)

    async def sign_in(slug: str) -> httpx.AsyncClient:
        client = make_client(app)
        response = await client.post(f'/api/demo/personas/{slug}/session')
        assert response.status_code == 200, response.text
        return client

    leader, member, path = await group(sign_in)
    endpoint = f'{path}/planning'
    context = (await leader.get(endpoint)).json()['context']
    context.update(
        destination='Chicago',
        start_date='2026-11-07',
        end_date='2026-11-07',
        timezone='America/Chicago',
    )
    await leader.put(f'{endpoint}/context', json=context)
    member_id = (await member.get('/api/me')).json()['id']
    await member.put(
        f'{path}/preferences/me',
        json={'budget_cents': 10000, 'dietary_notes': 'private diet marker'},
    )
    await member.post(
        f'{path}/concerns',
        json={'content': 'private concern marker', 'client_concern_id': str(uuid.uuid4())},
    )

    async def research(public: dict[str, Any], _settings: Settings) -> tuple[Draft, dict[str, Any]]:
        assert 'private diet marker' not in json.dumps(public)
        assert 'private concern marker' not in json.dumps(public)
        return sample_plan(
            date(2026, 11, 7), [uuid.UUID(m['account_id']) for m in public['members']]
        ), {'input_tokens': 100}

    async def assess(
        draft: Draft, private: list[dict[str, Any]], _settings: Settings
    ) -> tuple[Draft, dict[str, str]]:
        mine = next(p for p in private if p['account_id'] == member_id)
        assert mine['dietary_notes'] == 'private diet marker'
        assert mine['concerns'] == ['private concern marker']
        return draft, {p['account_id']: f'Only for {p["account_id"]}' for p in private}

    monkeypatch.setattr(tasks, 'research', research)
    monkeypatch.setattr(tasks, 'assess_candidates', assess)
    body = {'client_id': str(uuid.uuid4())}
    queued = await leader.post(f'{endpoint}/runs', json=body)
    assert queued.status_code == 202, queued.text
    assert (await leader.post(f'{endpoint}/runs', json=body)).json() == queued.json()
    assert (
        await leader.post(f'{endpoint}/runs', json={'client_id': str(uuid.uuid4())})
    ).status_code == 409
    # Simulate process loss after claiming; the next worker reclaims the expired lease.
    sync_conn.execute(
        """UPDATE pilot_runs SET status='running',attempts=1,
        lease_until=now()-interval '1 minute' WHERE id=%s""",
        (queued.json()['id'],),
    )
    assert await tasks.process_next()
    assert sync_conn.execute(
        'SELECT attempts FROM pilot_runs WHERE id=%s', (queued.json()['id'],)
    ).fetchone() == (2,)
    state = (await member.get(endpoint)).json()
    assert state['runs'][0]['status'] == 'completed'
    assert len(state['versions']) == 1
    assert state['my_explanations'] == {state['versions'][0]['id']: f'Only for {member_id}'}
    leader_state = await leader.get(endpoint)
    assert f'Only for {member_id}' not in leader_state.text
    events = sync_conn.execute(
        "SELECT payload::text FROM trip_events WHERE type='planning.changed'"
    ).fetchall()
    assert all(row[0] == '{}' for row in events)
    mine = (await member.get(f'{path}/concerns')).json()['mine'][0]
    assert (await member.post(f'{path}/concerns/{mine["id"]}/withdraw')).status_code == 200
    assert (await member.get(endpoint)).json()['my_explanations'] == {}
    assert (await leader.get(endpoint)).json()['my_explanations']


async def test_expired_worker_lease_recovers_and_stops_after_two_attempts(
    persona_client: PersonaClient,
    sync_conn: psycopg.Connection,
) -> None:
    from trippilot.planning.tasks import process_next

    leader, _, path = await group(persona_client)
    run_id = uuid.uuid4()
    sync_conn.execute(
        """INSERT INTO pilot_runs(id,trip_id,client_id,context_revision,status,attempts,lease_until)
        VALUES (%s,%s,%s,0,'running',2,now()-interval '1 minute')""",
        (run_id, path.rsplit('/', 1)[1], uuid.uuid4()),
    )
    assert await process_next()
    run = (await leader.get(f'{path}/planning')).json()['runs'][0]
    assert run['id'] == str(run_id)
    assert run['status'] == 'failed'
    assert not await process_next()


async def test_member_opt_out_redistributes_fixed_cost_and_needs_fresh_acceptance(
    persona_client: PersonaClient,
) -> None:
    leader, member, path = await group(persona_client)
    endpoint = f'{path}/planning'
    base = (await leader.post(f'{endpoint}/sample')).json()[0]
    await leader.post(f'{endpoint}/versions/{base["id"]}/select')
    member_id = (await member.get('/api/me')).json()['id']
    item = base['items'][1]
    created = await member.post(
        f'{endpoint}/proposals',
        json={
            'base_id': base['id'],
            'cancelled_item_id': item['id'],
            'opt_out': True,
        },
    )
    assert created.status_code == 201, created.text
    proposal = created.json()
    state = (await member.get(endpoint)).json()
    revision = next(v for v in state['versions'] if v['id'] == proposal['version_id'])
    changed_item = next(i for i in revision['items'] if i['id'] == item['id'])
    assert member_id not in changed_item['participants']
    assert changed_item['total_cents'] == item['total_cents']
    assert revision['total_cents'] == base['total_cents']
    assert sum(proposal['cost_differences'].values()) == 0
    assert proposal['cost_differences'][member_id] < 0
    assert proposal['responses'] == {}
    route = f'{endpoint}/proposals/{proposal["id"]}'
    response = {'version_id': revision['id'], 'response': 'accept'}
    await member.post(f'{route}/respond', json=response)
    assert (await leader.post(f'{route}/finalize')).status_code == 409
    await leader.post(f'{route}/respond', json={**response, 'response': 'alternative'})
    assert (await leader.post(f'{route}/finalize')).status_code == 409
    await leader.post(f'{route}/respond', json=response)
    assert (await leader.post(f'{route}/finalize')).status_code == 200
    assert (await member.get(endpoint)).json()['selected_id'] == revision['id']


async def test_requirement_priorities_are_private_and_invalidate_plans(
    persona_client: PersonaClient,
) -> None:
    leader, member, path = await group(persona_client)
    await leader.post(f'{path}/planning/sample')
    body = {'must_haves': 'step-free-marker', 'preferred': 'outdoor-lunch-marker'}
    saved = await member.put(f'{path}/preferences/me', json=body)
    assert saved.status_code == 200, saved.text
    own = (await member.get(f'{path}/preferences')).json()['mine']
    assert own['must_haves'] == body['must_haves']
    assert own['preferred'] == body['preferred']
    public = await leader.get(f'{path}/preferences')
    state = await leader.get(f'{path}/planning')
    for value in body.values():
        assert value not in public.text
        assert value not in state.text
    assert all(not v['current'] for v in state.json()['versions'])


async def test_selected_plan_stays_changeable_after_inputs_change(
    persona_client: PersonaClient,
) -> None:
    """A stale selected plan can still be opted out of, replaced and finalized."""
    leader, member, path = await group(persona_client)
    endpoint = f'{path}/planning'
    base, candidate = (await leader.post(f'{endpoint}/sample')).json()
    assert (await leader.post(f'{endpoint}/versions/{base["id"]}/select')).status_code == 200
    saved = await member.put(
        f'{path}/preferences/me', json={'interests': 'Architecture boat tours'}
    )
    assert saved.status_code == 200, saved.text
    stale = (await leader.get(endpoint)).json()
    assert all(not v['current'] for v in stale['versions'])
    assert stale['selected_id'] == base['id']

    opt_out = await member.post(
        f'{endpoint}/proposals',
        json={'base_id': base['id'], 'cancelled_item_id': base['items'][1]['id'], 'opt_out': True},
    )
    assert opt_out.status_code == 201, opt_out.text
    state = (await member.get(endpoint)).json()
    opted = next(v for v in state['versions'] if v['id'] == opt_out.json()['version_id'])
    assert opted['current']

    replacement = await leader.post(
        f'{endpoint}/proposals',
        json={
            'base_id': base['id'],
            'cancelled_item_id': base['items'][1]['id'],
            'candidate_version_id': candidate['id'],
            'candidate_item_id': candidate['items'][1]['id'],
        },
    )
    assert replacement.status_code == 201, replacement.text
    proposal = replacement.json()
    state = (await leader.get(endpoint)).json()
    revised = next(v for v in state['versions'] if v['id'] == proposal['version_id'])
    assert revised['current']

    route = f'{endpoint}/proposals/{proposal["id"]}'
    response = {'version_id': proposal['version_id'], 'response': 'accept'}
    assert (await leader.post(f'{route}/respond', json=response)).status_code == 200
    assert (await member.post(f'{route}/respond', json=response)).status_code == 200
    finalized = await leader.post(f'{route}/finalize')
    assert finalized.status_code == 200, finalized.text
    assert (await leader.get(endpoint)).json()['selected_id'] == proposal['version_id']

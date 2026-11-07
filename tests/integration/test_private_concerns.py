"""Private concerns: author view, anonymous leader view, and the privacy of events and logs."""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING

import psycopg
import pytest

if TYPE_CHECKING:
    import httpx
    from conftest import PersonaClient

Conn = psycopg.Connection[tuple[object, ...]]
TEXT = 'I can’t afford the boat tour'
LEADER_TEXT = 'I’d rather skip the early flight'


async def create_group(persona_client: PersonaClient) -> tuple[httpx.AsyncClient, str]:
    """Start a disposable demo group and return its leader and API path."""
    leader = await persona_client('maya')
    created = await leader.post('/api/trips', json={'name': 'Concerns test'})
    assert created.status_code == 201
    return leader, f'/api/trips/{created.json()["id"]}'


async def join(friend: httpx.AsyncClient, leader: httpx.AsyncClient, path: str) -> None:
    """Join using the same invite route as the browser."""
    token = (await leader.get(f'{path}/invite')).json()['url'].rsplit('/', 1)[1]
    joined = await friend.post(f'/api/invites/{token}/join')
    assert joined.status_code == 200, joined.text


def concern(content: str = TEXT) -> dict[str, str]:
    """Create a fresh send attempt, retained unchanged when testing retries."""
    return {'content': content, 'client_concern_id': str(uuid.uuid4())}


async def three(
    persona_client: PersonaClient,
) -> tuple[httpx.AsyncClient, httpx.AsyncClient, httpx.AsyncClient, str]:
    """Return the leader (maya), two members (sam, ana) and the trip API path."""
    leader, path = await create_group(persona_client)
    sam = await persona_client('sam')
    ana = await persona_client('ana')
    await join(sam, leader, path)
    await join(ana, leader, path)
    return leader, sam, ana, path


async def test_author_sees_own_concern_and_leader_sees_text_without_identity(
    persona_client: PersonaClient,
) -> None:
    leader, sam, _, path = await three(persona_client)
    body = concern()
    sent = await sam.post(f'{path}/concerns', json=body)
    assert sent.status_code == 201, sent.text
    view = sent.json()
    assert view['content'] == TEXT
    assert view['client_concern_id'] == body['client_concern_id']
    assert isinstance(view['id'], int)
    assert datetime.fromisoformat(view['created_at']).tzinfo is not None
    mine = (await sam.get(f'{path}/concerns')).json()
    assert mine == {'mine': [view], 'anonymous': None}
    seen = await leader.get(f'{path}/concerns')
    assert seen.status_code == 200
    data = seen.json()
    assert data['mine'] == []
    assert data['anonymous'] == [
        {'content': TEXT, 'submitted_on': data['anonymous'][0]['submitted_on']}
    ]
    assert set(data['anonymous'][0]) == {'content', 'submitted_on'}
    submitted = date.fromisoformat(data['anonymous'][0]['submitted_on'])
    assert abs((datetime.now(UTC).date() - submitted).days) <= 1
    sam_id = (await sam.get('/api/me')).json()['id']
    assert sam_id not in seen.text
    assert 'Sam' not in seen.text
    assert body['client_concern_id'] not in seen.text


async def test_other_member_sees_nothing(persona_client: PersonaClient) -> None:
    _, sam, ana, path = await three(persona_client)
    assert (await sam.post(f'{path}/concerns', json=concern())).status_code == 201
    seen = await ana.get(f'{path}/concerns')
    assert seen.json() == {'mine': [], 'anonymous': None}
    assert TEXT not in seen.text


async def test_leader_sees_own_concerns_only_in_mine(persona_client: PersonaClient) -> None:
    alone, alone_path = await create_group(persona_client)
    sent = await alone.post(f'{alone_path}/concerns', json=concern(LEADER_TEXT))
    assert sent.status_code == 201
    solo = (await alone.get(f'{alone_path}/concerns')).json()
    assert [item['id'] for item in solo['mine']] == [sent.json()['id']]
    assert solo['anonymous'] == []

    leader, sam, _, path = await three(persona_client)
    own = await leader.post(f'{path}/concerns', json=concern(LEADER_TEXT))
    other_body = concern()
    assert own.status_code == 201
    assert (await sam.post(f'{path}/concerns', json=other_body)).status_code == 201
    seen = await leader.get(f'{path}/concerns')
    data = seen.json()
    assert [item['content'] for item in data['mine']] == [LEADER_TEXT]
    assert [item['content'] for item in data['anonymous']] == [TEXT]
    assert set(data['anonymous'][0]) == {'content', 'submitted_on'}
    assert LEADER_TEXT not in [item['content'] for item in data['anonymous']]
    sam_id = (await sam.get('/api/me')).json()['id']
    assert sam_id not in seen.text
    assert 'Sam' not in seen.text
    assert other_body['client_concern_id'] not in seen.text

    second = await leader.post(f'{path}/concerns', json=concern('Another of mine'))
    assert second.status_code == 201
    withdrawn = await leader.post(f'{path}/concerns/{second.json()["id"]}/withdraw')
    assert withdrawn.status_code == 200
    after = withdrawn.json()
    assert [item['content'] for item in after['mine']] == [LEADER_TEXT]
    assert [item['content'] for item in after['anonymous']] == [TEXT]


async def test_lists_are_newest_first(persona_client: PersonaClient) -> None:
    leader, sam, ana, path = await three(persona_client)
    assert (await sam.post(f'{path}/concerns', json=concern('First'))).status_code == 201
    assert (await ana.post(f'{path}/concerns', json=concern('Second'))).status_code == 201
    assert (await sam.post(f'{path}/concerns', json=concern('Third'))).status_code == 201
    sams = (await sam.get(f'{path}/concerns')).json()
    assert [item['content'] for item in sams['mine']] == ['Third', 'First']
    seen = (await leader.get(f'{path}/concerns')).json()
    assert [item['content'] for item in seen['anonymous']] == ['Third', 'Second', 'First']


async def test_retries_are_idempotent_and_conflicting_reuse_is_rejected(
    persona_client: PersonaClient, sync_conn: Conn
) -> None:
    _, sam, _, path = await three(persona_client)
    trip_id = path.rsplit('/', 1)[1]
    body = concern()
    replies = await asyncio.gather(*(sam.post(f'{path}/concerns', json=body) for _ in range(3)))
    assert all(r.status_code == 201 for r in replies)
    assert len({r.json()['id'] for r in replies}) == 1
    rows = sync_conn.execute(
        'SELECT count(*) FROM private_concerns WHERE trip_id = %s', (trip_id,)
    ).fetchone()
    assert rows == (1,)
    events = sync_conn.execute(
        "SELECT count(*) FROM trip_events WHERE trip_id = %s AND type = 'concerns.changed'",
        (trip_id,),
    ).fetchone()
    assert events == (1,)
    conflict = await sam.post(f'{path}/concerns', json={**body, 'content': 'Different text'})
    assert conflict.status_code == 409


async def test_withdraw_erases_text_hides_from_both_views_and_blocks_resurrection(
    persona_client: PersonaClient, sync_conn: Conn
) -> None:
    leader, sam, ana, path = await three(persona_client)
    trip_id = path.rsplit('/', 1)[1]
    body = concern()
    concern_id = (await sam.post(f'{path}/concerns', json=body)).json()['id']
    assert (await leader.post(f'{path}/concerns/{concern_id}/withdraw')).status_code == 404
    assert (await ana.post(f'{path}/concerns/{concern_id}/withdraw')).status_code == 404
    withdrawn = await sam.post(f'{path}/concerns/{concern_id}/withdraw')
    assert withdrawn.status_code == 200
    assert withdrawn.json() == {'mine': [], 'anonymous': None}
    assert (await leader.get(f'{path}/concerns')).json()['anonymous'] == []
    row = sync_conn.execute(
        'SELECT content, withdrawn_at FROM private_concerns WHERE trip_id = %s', (trip_id,)
    ).fetchone()
    assert row is not None
    assert row[0] is None
    assert row[1] is not None
    replay = await sam.post(f'{path}/concerns', json=body)
    assert replay.status_code == 409
    assert (await sam.get(f'{path}/concerns')).json()['mine'] == []
    again = await sam.post(f'{path}/concerns/{concern_id}/withdraw')
    assert again.status_code == 200
    events = sync_conn.execute(
        "SELECT count(*) FROM trip_events WHERE trip_id = %s AND type = 'concerns.changed'",
        (trip_id,),
    ).fetchone()
    assert events == (2,)
    unknown = await sam.post(f'{path}/concerns/999999/withdraw')
    assert unknown.status_code == 404


async def test_events_and_logs_carry_no_private_values(
    persona_client: PersonaClient,
    sync_conn: Conn,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    caplog.set_level(logging.DEBUG)
    _, sam, _, path = await three(persona_client)
    trip_id = path.rsplit('/', 1)[1]
    body = concern()
    concern_id = (await sam.post(f'{path}/concerns', json=body)).json()['id']
    assert (await sam.post(f'{path}/concerns/{concern_id}/withdraw')).status_code == 200
    rows = sync_conn.execute(
        'SELECT type, payload::text FROM trip_events WHERE trip_id = %s', (trip_id,)
    ).fetchall()
    changed = [row for row in rows if row[0] == 'concerns.changed']
    assert len(changed) == 2
    assert all(row[1] == '{}' for row in changed)
    for _, payload in rows:
        assert isinstance(payload, str)
        assert TEXT not in payload
        assert body['client_concern_id'] not in payload
    captured = capsys.readouterr()
    assert TEXT not in caplog.text
    assert TEXT not in captured.out
    assert TEXT not in captured.err
    assert 'boat tour' not in caplog.text + captured.out + captured.err


@pytest.mark.parametrize('exit_method', ['leave', 'remove'])
async def test_departed_member_loses_access(
    persona_client: PersonaClient, exit_method: str
) -> None:
    leader, sam, _, path = await three(persona_client)
    body = concern()
    concern_id = (await sam.post(f'{path}/concerns', json=body)).json()['id']
    if exit_method == 'leave':
        await sam.post(f'{path}/leave')
    else:
        account_id = (await sam.get('/api/me')).json()['id']
        await leader.post(f'{path}/members/{account_id}/remove')
    assert (await sam.get(f'{path}/concerns')).status_code == 404
    assert (await sam.post(f'{path}/concerns', json=concern())).status_code == 404
    assert (await sam.post(f'{path}/concerns/{concern_id}/withdraw')).status_code == 404
    kept = (await leader.get(f'{path}/concerns')).json()['anonymous']
    assert [item['content'] for item in kept] == [TEXT]


@pytest.mark.parametrize('content', ['', '   ', 'a' * 1001])
async def test_invalid_input_is_rejected(persona_client: PersonaClient, content: str) -> None:
    leader, path = await create_group(persona_client)
    assert (await leader.post(f'{path}/concerns', json=concern(content))).status_code == 422
    assert (
        await leader.post(f'{path}/concerns', json={**concern(), 'account_id': str(uuid.uuid4())})
    ).status_code == 422
    assert (await leader.get(f'{path}/concerns')).json()['mine'] == []


async def test_length_boundary_is_accepted(persona_client: PersonaClient) -> None:
    leader, path = await create_group(persona_client)
    assert (await leader.post(f'{path}/concerns', json=concern('x' * 1000))).status_code == 201


async def test_open_concern_cap(persona_client: PersonaClient) -> None:
    leader, path = await create_group(persona_client)
    first_id = None
    for index in range(20):
        sent = await leader.post(f'{path}/concerns', json=concern(f'Concern {index}'))
        assert sent.status_code == 201
        first_id = first_id or sent.json()['id']
    assert (await leader.post(f'{path}/concerns', json=concern('One too many'))).status_code == 409
    assert (await leader.post(f'{path}/concerns/{first_id}/withdraw')).status_code == 200
    assert (await leader.post(f'{path}/concerns', json=concern('Fits now'))).status_code == 201


async def test_strangers_and_signed_out_callers_are_refused(
    persona_client: PersonaClient,
) -> None:
    leader, path = await create_group(persona_client)
    outsider = await persona_client('ana')
    assert (await outsider.get(f'{path}/concerns')).status_code == 404
    assert (await outsider.post(f'{path}/concerns', json=concern())).status_code == 404
    await leader.post('/api/auth/signout')
    assert (await leader.get(f'{path}/concerns')).status_code == 401
    assert (await leader.post(f'{path}/concerns', json=concern())).status_code == 401


async def test_openapi_leader_projection_is_allowlisted(persona_client: PersonaClient) -> None:
    leader, _ = await create_group(persona_client)
    schema = (await leader.get('/openapi.json')).json()
    props = schema['components']['schemas']['AnonymousConcernView']['properties']
    assert set(props) == {'content', 'submitted_on'}


async def test_deleting_the_trip_removes_its_concerns(
    persona_client: PersonaClient, sync_conn: Conn
) -> None:
    leader, path = await create_group(persona_client)
    trip_id = path.rsplit('/', 1)[1]
    assert (await leader.post(f'{path}/concerns', json=concern())).status_code == 201
    assert (await leader.delete(path)).status_code in (200, 204)
    count = sync_conn.execute(
        'SELECT count(*) FROM private_concerns WHERE trip_id = %s', (trip_id,)
    ).fetchone()
    assert count == (0,)

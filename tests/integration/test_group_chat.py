"""Group chat persistence, retry behavior, pagination and membership boundaries."""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

import psycopg
import pytest

if TYPE_CHECKING:
    import httpx
    from conftest import PersonaClient

Conn = psycopg.Connection[tuple[object, ...]]


async def create_group(persona_client: PersonaClient) -> tuple[httpx.AsyncClient, str]:
    """Start a disposable demo group and return its leader and API path."""
    leader = await persona_client('maya')
    created = await leader.post('/api/trips', json={'name': 'Chat test'})
    assert created.status_code == 201
    return leader, f'/api/trips/{created.json()["id"]}'


async def join(friend: httpx.AsyncClient, leader: httpx.AsyncClient, path: str) -> None:
    """Join using the same invite route as the browser."""
    token = (await leader.get(f'{path}/invite')).json()['url'].rsplit('/', 1)[1]
    joined = await friend.post(f'/api/invites/{token}/join')
    assert joined.status_code == 200, joined.text


def message(content: str = 'Let’s visit the museum') -> dict[str, str]:
    """Create a fresh send attempt, retained unchanged when testing retries."""
    return {'content': content, 'client_message_id': str(uuid.uuid4())}


async def test_message_roundtrip_keeps_text_and_author_without_private_fields(
    persona_client: PersonaClient, sync_conn: Conn
) -> None:
    leader, path = await create_group(persona_client)
    await leader.put(
        f'{path}/preferences/me', json={'dietary_notes': 'Private note', 'budget_cents': 12345}
    )
    sent = await leader.post(
        f'{path}/messages', json=message('  Hello\n<script>alert(1)</script>  ')
    )
    assert sent.status_code == 201, sent.text
    view = sent.json()
    assert view['author_name'] == 'Maya'
    assert view['account_id'] == (await leader.get('/api/me')).json()['id']
    assert view['content'] == 'Hello\n<script>alert(1)</script>'
    assert datetime.fromisoformat(view['created_at']).tzinfo is not None
    history = await leader.get(f'{path}/messages')
    assert history.json() == {'messages': [view], 'older_cursor': None}
    assert 'Private note' not in history.text and '12345' not in history.text
    events = sync_conn.execute(
        "SELECT payload FROM trip_events WHERE trip_id = %s AND type = 'message.created'",
        (path.rsplit('/', 1)[1],),
    ).fetchall()
    assert events == [({'message_id': view['id']},)]


async def test_repeated_and_concurrent_sends_create_one_message_and_event(
    persona_client: PersonaClient, sync_conn: Conn
) -> None:
    leader, path = await create_group(persona_client)
    body = message()
    replies = await asyncio.gather(*(leader.post(f'{path}/messages', json=body) for _ in range(3)))
    assert all(r.status_code == 201 for r in replies)
    assert len({r.json()['id'] for r in replies}) == 1
    assert len((await leader.get(f'{path}/messages')).json()['messages']) == 1
    count = sync_conn.execute(
        "SELECT count(*) FROM trip_events WHERE trip_id = %s AND type = 'message.created'",
        (path.rsplit('/', 1)[1],),
    ).fetchone()
    assert count == (1,)
    conflict = await leader.post(f'{path}/messages', json={**body, 'content': 'Different text'})
    assert conflict.status_code == 409


async def test_client_message_ids_are_scoped_to_sender_and_trip(
    persona_client: PersonaClient,
) -> None:
    leader, path = await create_group(persona_client)
    friend = await persona_client('sam')
    await join(friend, leader, path)
    body = message()
    first = await leader.post(f'{path}/messages', json=body)
    second = await friend.post(f'{path}/messages', json=body)
    assert first.status_code == second.status_code == 201
    assert first.json()['id'] != second.json()['id']
    other = (await leader.post('/api/trips', json={'name': 'Separate chat'})).json()['id']
    assert (await leader.get(f'/api/trips/{other}/messages')).json()['messages'] == []
    assert (await leader.post(f'/api/trips/{other}/messages', json=body)).status_code == 201
    assert len((await leader.get(f'{path}/messages')).json()['messages']) == 2


async def test_history_paginates_backwards_without_gaps_after_new_messages(
    persona_client: PersonaClient,
) -> None:
    leader, path = await create_group(persona_client)
    for index in range(7):
        assert (
            await leader.post(f'{path}/messages', json=message(f'Message {index}'))
        ).status_code == 201
    recent = (await leader.get(f'{path}/messages', params={'limit': 3})).json()
    assert [m['content'] for m in recent['messages']] == ['Message 4', 'Message 5', 'Message 6']
    await leader.post(f'{path}/messages', json=message('New arrival'))
    older = (
        await leader.get(f'{path}/messages', params={'limit': 3, 'before': recent['older_cursor']})
    ).json()
    assert [m['content'] for m in older['messages']] == ['Message 1', 'Message 2', 'Message 3']
    oldest = (
        await leader.get(f'{path}/messages', params={'limit': 3, 'before': older['older_cursor']})
    ).json()
    assert [m['content'] for m in oldest['messages']] == ['Message 0']
    assert oldest['older_cursor'] is None


@pytest.mark.parametrize('content', ['', '   \n ', 'a' * 4001])
async def test_invalid_message_does_not_create_history(
    persona_client: PersonaClient, content: str
) -> None:
    leader, path = await create_group(persona_client)
    invalid = await leader.post(f'{path}/messages', json=message(content))
    assert invalid.status_code == 422
    assert (await leader.get(f'{path}/messages')).json()['messages'] == []


async def test_length_boundary_and_caller_cannot_spoof_author(
    persona_client: PersonaClient,
) -> None:
    leader, path = await create_group(persona_client)
    assert (await leader.post(f'{path}/messages', json=message('x' * 4000))).status_code == 201
    spoof = await leader.post(
        f'{path}/messages', json={**message(), 'account_id': str(uuid.uuid4())}
    )
    assert spoof.status_code == 422
    assert len((await leader.get(f'{path}/messages')).json()['messages']) == 1


@pytest.mark.parametrize('exit_method', ['leave', 'remove'])
async def test_only_current_members_can_read_send_or_replay_a_message(
    persona_client: PersonaClient, exit_method: str
) -> None:
    leader, path = await create_group(persona_client)
    friend = await persona_client('sam')
    body = message()
    assert (await friend.get(f'{path}/messages')).status_code == 404
    assert (await friend.post(f'{path}/messages', json=body)).status_code == 404
    await join(friend, leader, path)
    assert (await friend.post(f'{path}/messages', json=body)).status_code == 201
    if exit_method == 'leave':
        await friend.post(f'{path}/leave')
    else:
        account_id = (await friend.get('/api/me')).json()['id']
        await leader.post(f'{path}/members/{account_id}/remove')
    assert (await friend.get(f'{path}/messages')).status_code == 404
    assert (await friend.post(f'{path}/messages', json=body)).status_code == 404
    assert len((await leader.get(f'{path}/messages')).json()['messages']) == 1


async def test_signed_out_requests_and_invalid_cursors_are_rejected(
    persona_client: PersonaClient,
) -> None:
    leader, path = await create_group(persona_client)
    for params in ({'before': 0}, {'limit': 0}, {'limit': 101}):
        assert (await leader.get(f'{path}/messages', params=params)).status_code == 422
    await leader.post('/api/auth/signout')
    assert (await leader.get(f'{path}/messages')).status_code == 401
    assert (await leader.post(f'{path}/messages', json=message())).status_code == 401

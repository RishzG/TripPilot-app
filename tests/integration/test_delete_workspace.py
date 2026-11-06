"""Only an organiser-only active workspace can be deleted; joins take the same lock."""

from __future__ import annotations

import asyncio
import uuid
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from conftest import PersonaClient


async def test_delete_empty_workspace_removes_preferences_and_invalidates_invite(
    persona_client: PersonaClient,
) -> None:
    leader = await persona_client('maya')
    trip_id = (await leader.post('/api/trips', json={'name': 'Disposable workspace'})).json()['id']
    path = f'/api/trips/{trip_id}'
    invite = (await leader.get(f'{path}/invite')).json()['url'].rsplit('/', 1)[1]
    saved = await leader.put(f'{path}/preferences/me', json={'origin': 'Chicago'})
    assert saved.status_code == 200
    assert (await leader.get(path)).json()['can_delete'] is True
    deleted = await leader.delete(path)
    assert deleted.status_code == 200, deleted.text
    assert deleted.json() == {'id': trip_id, 'deleted': True}
    assert (await leader.get(path)).status_code == 404
    assert (await leader.get(f'{path}/preferences')).status_code == 404
    assert (await leader.get(f'/api/invites/{invite}')).status_code == 404
    assert all(t['id'] != trip_id for t in (await leader.get('/api/trips')).json())
    assert (await leader.delete(path)).status_code == 404


@pytest.mark.parametrize('member_status', ['active', 'left', 'removed'])
async def test_deletion_is_allowed_only_after_all_other_members_leave_or_are_removed(
    persona_client: PersonaClient, member_status: str
) -> None:
    leader = await persona_client('maya')
    friend = await persona_client('sam')
    trip_id = (await leader.post('/api/trips', json={'name': 'Shared workspace'})).json()['id']
    path = f'/api/trips/{trip_id}'
    invite = (await leader.get(f'{path}/invite')).json()['url'].rsplit('/', 1)[1]
    assert (await friend.delete(path)).status_code == 404
    assert (await friend.post(f'/api/invites/{invite}/join')).status_code == 200
    assert (await friend.delete(path)).status_code == 403
    if member_status == 'left':
        assert (await friend.post(f'{path}/leave')).status_code == 200
    elif member_status == 'removed':
        friend_id = (await friend.get('/api/me')).json()['id']
        assert (await leader.post(f'{path}/members/{friend_id}/remove')).status_code == 200
    allowed = member_status != 'active'
    assert (await leader.get(path)).json()['can_delete'] is allowed
    assert (await leader.delete(path)).status_code == (200 if allowed else 409)
    assert (await leader.get(path)).status_code == (404 if allowed else 200)


async def test_delete_requires_a_session_and_does_not_disclose_unknown_trip(
    persona_client: PersonaClient,
) -> None:
    leader = await persona_client('maya')
    path = f'/api/trips/{uuid.uuid4()}'
    assert (await leader.delete(path)).status_code == 404
    await leader.post('/api/auth/signout')
    assert (await leader.delete(path)).status_code == 401


async def test_every_other_member_must_be_inactive_and_readding_blocks_delete(
    persona_client: PersonaClient,
) -> None:
    leader = await persona_client('maya')
    sam = await persona_client('sam')
    ana = await persona_client('ana')
    trip_id = (await leader.post('/api/trips', json={'name': 'All members check'})).json()['id']
    path = f'/api/trips/{trip_id}'
    invite = (await leader.get(f'{path}/invite')).json()['url'].rsplit('/', 1)[1]
    for member in (sam, ana):
        assert (await member.post(f'/api/invites/{invite}/join')).status_code == 200
    sam_id = (await sam.get('/api/me')).json()['id']
    assert (await leader.post(f'{path}/members/{sam_id}/remove')).status_code == 200
    assert (await leader.delete(path)).status_code == 409
    assert (await ana.post(f'{path}/leave')).status_code == 200
    assert (await leader.get(path)).json()['can_delete'] is True
    assert (await leader.post(f'{path}/members/{sam_id}/readd')).status_code == 200
    assert (await leader.get(path)).json()['can_delete'] is False
    assert (await leader.delete(path)).status_code == 409
    assert (await leader.post(f'{path}/members/{sam_id}/remove')).status_code == 200
    assert (await leader.delete(path)).status_code == 200


async def test_join_racing_delete_never_deletes_a_workspace_with_a_joined_member(
    persona_client: PersonaClient,
) -> None:
    leader = await persona_client('maya')
    friend = await persona_client('sam')
    trip_id = (await leader.post('/api/trips', json={'name': 'Race check'})).json()['id']
    path = f'/api/trips/{trip_id}'
    invite = (await leader.get(f'{path}/invite')).json()['url'].rsplit('/', 1)[1]
    joined, deleted = await asyncio.gather(
        friend.post(f'/api/invites/{invite}/join'), leader.delete(path)
    )
    assert (joined.status_code, deleted.status_code) in ((200, 409), (404, 200))

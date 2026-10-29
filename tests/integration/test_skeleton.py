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


def test_seam_routers_have_their_prefixes_and_only_planned_routes(make_app: MakeApp) -> None:
    from trippilot.admin import router as admin_router
    from trippilot.payments import router as payments_router

    # The payments router includes the webhook router, so its own route list holds an include
    # marker rather than flat paths; the app's OpenAPI document lists the real paths.
    paths = set(make_app(False).openapi()['paths'])
    payments_paths = {path for path in paths if path.startswith('/api/paypal')}

    assert payments_router.router.prefix == '/api/paypal'
    assert admin_router.router.prefix == '/api/admin'
    assert payments_paths == {
        '/api/paypal/config',
        '/api/paypal/vault/setup-token',
        '/api/paypal/vault/payment-token',
        '/api/paypal/vault/status',
        '/api/paypal/vault',
        '/api/paypal/webhooks',
        '/api/paypal/pool/buyers',  # plan 01-14: admin-only pool enrolment
        '/api/paypal/pool/{slug}/setup-token',
        '/api/paypal/pool/{slug}/payment-token',
    }
    assert {path for path in paths if path.startswith('/api/admin')} == {
        '/api/admin/sandbox-checks'
    }


def test_app_mounts_the_payments_and_the_admin_routes(
    make_app: MakeApp,
) -> None:
    paths = set(make_app(False).openapi()['paths'])

    assert '/api/admin/sandbox-checks' in paths
    assert {'/api/paypal/config', '/api/paypal/vault/status'} <= paths
    assert '/api/trips' in paths
    assert '/api/trips/{trip_id}' in paths


def test_realtime_jobs_and_payments_tasks_packages_import() -> None:
    import importlib

    for name in ('trippilot.realtime', 'trippilot.jobs', 'trippilot.payments.tasks'):
        assert importlib.import_module(name).__name__ == name

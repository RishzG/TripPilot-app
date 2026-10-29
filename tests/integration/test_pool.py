"""The simulated-friends buyer pool: admin enrolment API and leasing (plan 01-14, ACC-03, D-17).

FakePayPal only. `ledger_entries` rows persist across tests (01-19), so ledger assertions look up
this test's rows by a unique actor id and never count totals.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Iterator
from datetime import timedelta
from typing import TYPE_CHECKING

import httpx
import psycopg
import pytest
from cryptography.fernet import Fernet
from fastapi import FastAPI
from pydantic import SecretStr

from trippilot.app import create_app
from trippilot.payments import get_paypal_gateway
from trippilot.payments.fake import FakePayPal
from trippilot.settings import Settings, get_settings

if TYPE_CHECKING:
    from conftest import MakeClient, MakeMember
    from sqlalchemy.ext.asyncio import AsyncSession

Conn = psycopg.Connection[tuple[object, ...]]
ADMIN_EMAIL = 'team.lead@example.com'
BUYERS = '/api/paypal/pool/buyers'


def _cookie(raw: str) -> dict[str, str]:
    """Return a Cookie header carrying the raw session value."""
    return {'Cookie': f'tp_session={raw}'}


@pytest.fixture
def fake() -> FakePayPal:
    """Return the fake PayPal every request in a test talks to."""
    return FakePayPal()


@pytest.fixture
def settings() -> Settings:
    """Return settings with an admin list, a fresh vault key and the fake PayPal mode."""
    return get_settings().model_copy(
        update={
            'demo_mode': True,
            'paypal_mode': 'fake',
            'paypal_client_id': 'test-client-id-not-a-secret',
            'admin_emails': [ADMIN_EMAIL],
            'vault_keys': SecretStr(Fernet.generate_key().decode()),
        }
    )


@pytest.fixture
def app(settings: Settings, fake: FakePayPal) -> Iterator[FastAPI]:
    """Return a demo-mode app wired to FakePayPal."""
    built = create_app(settings)
    built.dependency_overrides[get_paypal_gateway] = lambda: fake
    yield built


async def _admin(make_member: MakeMember, sync_conn: Conn) -> str:
    """Create a member on the admin list and return the raw session cookie value."""
    account, raw = await make_member('Lead')
    sync_conn.execute('UPDATE accounts SET email = %s WHERE id = %s', (ADMIN_EMAIL, account.id))
    return raw


async def _add(http: httpx.AsyncClient, raw: str, slug: str = 'maya') -> httpx.Response:
    """Add a pending pool buyer as the admin whose cookie is `raw`."""
    return await http.post(
        BUYERS,
        json={
            'slug': slug,
            'persona_slug': slug,
            'sandbox_email': f'sb-{slug}@personal.example.com',
        },
        headers=_cookie(raw),
    )


async def _enrol(http: httpx.AsyncClient, raw: str, slug: str) -> httpx.Response:
    """Run the pool setup-token then payment-token calls; return the payment-token answer."""
    setup = await http.post(f'/api/paypal/pool/{slug}/setup-token', headers=_cookie(raw))
    assert setup.status_code == 200, setup.text
    return await http.post(
        f'/api/paypal/pool/{slug}/payment-token',
        json={'vaultSetupToken': setup.json()['vaultSetupToken']},
        headers=_cookie(raw),
    )


def _scalar(conn: Conn, query: str, params: tuple[object, ...] = ()) -> object:
    """Return the first column of the first row of a query."""
    row = conn.execute(query, params).fetchone()
    assert row is not None
    return row[0]


# -- admin gating (T-01-41) ---------------------------------------------------------------------


async def test_every_pool_route_is_403_for_a_member_outside_the_admin_list(
    app: FastAPI, make_client: MakeClient, make_member: MakeMember
) -> None:
    _, raw = await make_member('Other')
    http = make_client(app)

    answers = [
        await http.get(BUYERS, headers=_cookie(raw)),
        await http.post(
            BUYERS, json={'slug': 'maya', 'persona_slug': 'maya'}, headers=_cookie(raw)
        ),
        await http.post('/api/paypal/pool/maya/setup-token', headers=_cookie(raw)),
        await http.post(
            '/api/paypal/pool/maya/payment-token',
            json={'vaultSetupToken': 'x'},
            headers=_cookie(raw),
        ),
    ]

    assert [a.status_code for a in answers] == [403, 403, 403, 403]


async def test_every_pool_route_is_401_when_signed_out(
    app: FastAPI, make_client: MakeClient
) -> None:
    http = make_client(app)

    answers = [
        await http.get(BUYERS),
        await http.post(BUYERS, json={'slug': 'maya'}),
        await http.post('/api/paypal/pool/maya/setup-token'),
        await http.post('/api/paypal/pool/maya/payment-token', json={'vaultSetupToken': 'x'}),
    ]

    assert [a.status_code for a in answers] == [401, 401, 401, 401]


async def test_a_persona_session_is_403_even_when_its_email_is_on_the_admin_list(
    app: FastAPI, make_client: MakeClient, sync_conn: Conn
) -> None:
    http = make_client(app)
    signed_in = await http.post('/api/demo/personas/maya/session')
    assert signed_in.status_code == 200, signed_in.text
    sync_conn.execute("UPDATE accounts SET email = %s WHERE persona_slug = 'maya'", (ADMIN_EMAIL,))

    answers = [
        await http.get(BUYERS),
        await http.post(BUYERS, json={'slug': 'ana', 'persona_slug': 'ana'}),
        await http.post('/api/paypal/pool/ana/setup-token'),
    ]

    assert [a.status_code for a in answers] == [403, 403, 403]
    assert _scalar(sync_conn, 'SELECT count(*) FROM pool_buyers') == 0


# -- adding and listing buyers ------------------------------------------------------------------


async def test_an_admin_adds_a_pending_buyer_for_the_current_environment(
    app: FastAPI,
    settings: Settings,
    make_client: MakeClient,
    make_member: MakeMember,
    sync_conn: Conn,
) -> None:
    raw = await _admin(make_member, sync_conn)
    http = make_client(app)

    response = await _add(http, raw, 'maya')

    assert response.status_code == 201, response.text
    assert response.json() == {
        'slug': 'maya',
        'persona_slug': 'maya',
        'sandbox_email': 'sb-maya@personal.example.com',
        'status': 'pending',
    }
    row = sync_conn.execute(
        'SELECT environment, status, vault_token_id FROM pool_buyers WHERE slug = %s', ('maya',)
    ).fetchone()
    assert row == (settings.app_env, 'pending', None)


async def test_adding_the_same_slug_twice_is_409_and_keeps_one_row(
    app: FastAPI, make_client: MakeClient, make_member: MakeMember, sync_conn: Conn
) -> None:
    raw = await _admin(make_member, sync_conn)
    http = make_client(app)
    await _add(http, raw, 'maya')

    again = await _add(http, raw, 'maya')

    assert again.status_code == 409
    assert _scalar(sync_conn, "SELECT count(*) FROM pool_buyers WHERE slug = 'maya'") == 1


@pytest.mark.parametrize('slug', ['', 'Maya', 'has space', '../x', 'x' * 40])
async def test_a_malformed_slug_is_422_and_nothing_is_stored(
    app: FastAPI, make_client: MakeClient, make_member: MakeMember, sync_conn: Conn, slug: str
) -> None:
    raw = await _admin(make_member, sync_conn)
    http = make_client(app)

    response = await _add(http, raw, slug)

    assert response.status_code == 422
    assert _scalar(sync_conn, 'SELECT count(*) FROM pool_buyers') == 0


async def test_the_list_shows_slug_persona_email_and_status_and_never_a_token_id(
    app: FastAPI,
    make_client: MakeClient,
    make_member: MakeMember,
    fake: FakePayPal,
    sync_conn: Conn,
) -> None:
    raw = await _admin(make_member, sync_conn)
    http = make_client(app)
    await _add(http, raw, 'maya')
    await _add(http, raw, 'sam')
    await _enrol(http, raw, 'maya')

    response = await http.get(BUYERS, headers=_cookie(raw))

    assert response.status_code == 200
    buyers = {row['slug']: row for row in response.json()}
    assert set(buyers) == {'maya', 'sam'}
    assert {key for row in buyers.values() for key in row} == {
        'slug',
        'persona_slug',
        'sandbox_email',
        'status',
    }
    assert buyers['maya']['status'] == 'enrolled'
    assert buyers['sam']['status'] == 'pending'
    assert buyers['maya']['sandbox_email'] == 'sb-maya@personal.example.com'
    (token,) = fake.payment_tokens.values()
    for secret in (token.id, token.customer_id or '', token.payer_id or ''):
        assert secret not in response.text


# -- enrolment through vault_flow ---------------------------------------------------------------


async def test_enrolling_stores_one_encrypted_pool_buyer_token_and_marks_the_buyer_enrolled(
    app: FastAPI,
    make_client: MakeClient,
    make_member: MakeMember,
    fake: FakePayPal,
    sync_conn: Conn,
) -> None:
    raw = await _admin(make_member, sync_conn)
    http = make_client(app)
    await _add(http, raw, 'maya')

    saved = await _enrol(http, raw, 'maya')

    assert saved.status_code == 200, saved.text
    assert saved.json()['status'] == 'enrolled'
    (token,) = fake.payment_tokens.values()
    for secret in (token.id, token.customer_id or ''):
        assert secret not in saved.text
    buyer_id, status, vault_token_id = sync_conn.execute(
        'SELECT id, status, vault_token_id FROM pool_buyers WHERE slug = %s', ('maya',)
    ).fetchone() or (None, None, None)
    assert status == 'enrolled'
    rows = sync_conn.execute(
        'SELECT id, owner_kind, owner_id, key_version, row_to_json(v)::text FROM vault_tokens v'
    ).fetchall()
    assert len(rows) == 1
    assert rows[0][0] == vault_token_id
    assert (rows[0][1], rows[0][2]) == ('pool_buyer', buyer_id)
    assert token.id not in str(rows[0][4])
    assert token.customer_id is not None
    assert token.customer_id not in str(rows[0][4])


async def test_re_enrolling_replaces_the_token_and_keeps_one_active_row(
    app: FastAPI,
    make_client: MakeClient,
    make_member: MakeMember,
    fake: FakePayPal,
    sync_conn: Conn,
) -> None:
    raw = await _admin(make_member, sync_conn)
    http = make_client(app)
    await _add(http, raw, 'maya')
    await _enrol(http, raw, 'maya')
    (first,) = fake.payment_tokens.values()

    second = await _enrol(http, raw, 'maya')

    assert second.status_code == 200
    assert first.id not in fake.payment_tokens
    assert len(fake.payment_tokens) == 1
    active = sync_conn.execute(
        "SELECT id FROM vault_tokens WHERE owner_kind = 'pool_buyer' AND deleted_at IS NULL"
    ).fetchall()
    assert len(active) == 1
    assert _scalar(sync_conn, 'SELECT count(*) FROM vault_tokens') == 2
    assert (
        _scalar(sync_conn, "SELECT vault_token_id FROM pool_buyers WHERE slug = 'maya'")
        == active[0][0]
    )


async def test_enrolling_writes_a_ledger_row_for_the_admin(
    app: FastAPI, make_client: MakeClient, make_member: MakeMember, sync_conn: Conn
) -> None:
    account, raw = await make_member('Lead')
    sync_conn.execute('UPDATE accounts SET email = %s WHERE id = %s', (ADMIN_EMAIL, account.id))
    http = make_client(app)
    await _add(http, raw, 'maya')

    await _enrol(http, raw, 'maya')

    actions = [
        row[0]
        for row in sync_conn.execute(
            'SELECT action FROM ledger_entries WHERE actor_id = %s ORDER BY id',
            (str(account.id),),
        )
    ]
    assert actions == ['vault.saved']


async def test_setup_for_an_unknown_buyer_is_404_and_creates_nothing(
    app: FastAPI,
    make_client: MakeClient,
    make_member: MakeMember,
    fake: FakePayPal,
    sync_conn: Conn,
) -> None:
    raw = await _admin(make_member, sync_conn)
    http = make_client(app)

    response = await http.post('/api/paypal/pool/nobody/setup-token', headers=_cookie(raw))

    assert response.status_code == 404
    assert response.json() == {'detail': 'not_found'}
    assert fake.calls == []
    assert _scalar(sync_conn, 'SELECT count(*) FROM pending_vault_setups') == 0


async def test_a_retired_buyer_cannot_be_enrolled(
    app: FastAPI, make_client: MakeClient, make_member: MakeMember, sync_conn: Conn
) -> None:
    raw = await _admin(make_member, sync_conn)
    http = make_client(app)
    await _add(http, raw, 'maya')
    sync_conn.execute("UPDATE pool_buyers SET status = 'retired' WHERE slug = 'maya'")

    response = await http.post('/api/paypal/pool/maya/setup-token', headers=_cookie(raw))

    assert response.status_code == 409


async def test_a_setup_token_started_for_one_buyer_cannot_enrol_another(
    app: FastAPI,
    make_client: MakeClient,
    make_member: MakeMember,
    fake: FakePayPal,
    sync_conn: Conn,
) -> None:
    raw = await _admin(make_member, sync_conn)
    http = make_client(app)
    await _add(http, raw, 'maya')
    await _add(http, raw, 'sam')
    setup = await http.post('/api/paypal/pool/maya/setup-token', headers=_cookie(raw))

    crossed = await http.post(
        '/api/paypal/pool/sam/payment-token',
        json={'vaultSetupToken': setup.json()['vaultSetupToken']},
        headers=_cookie(raw),
    )

    assert crossed.status_code == 403
    assert fake.payment_tokens == {}
    assert _scalar(sync_conn, 'SELECT count(*) FROM vault_tokens') == 0


async def test_an_account_vault_setup_token_cannot_enrol_a_pool_buyer(
    app: FastAPI,
    make_client: MakeClient,
    make_member: MakeMember,
    sync_conn: Conn,
) -> None:
    raw = await _admin(make_member, sync_conn)
    http = make_client(app)
    await _add(http, raw, 'maya')
    own = await http.post('/api/paypal/vault/setup-token', headers=_cookie(raw))

    crossed = await http.post(
        '/api/paypal/pool/maya/payment-token',
        json={'vaultSetupToken': own.json()['vaultSetupToken']},
        headers=_cookie(raw),
    )

    assert crossed.status_code == 403


# -- leasing (D-17) -----------------------------------------------------------------------------


def _seed_buyers(
    conn: Conn, slugs: list[str], *, status: str = 'enrolled', environment: str = 'test'
) -> dict[str, uuid.UUID]:
    """Insert pool buyers (with a stand-in vault token when enrolled) and return slug -> id."""
    ids: dict[str, uuid.UUID] = {}
    for slug in slugs:
        buyer_id = uuid.uuid4()
        token_id: uuid.UUID | None = None
        if status == 'enrolled':
            token_id = uuid.uuid4()
            conn.execute(
                'INSERT INTO vault_tokens (id, owner_kind, owner_id, token_ciphertext, key_version)'
                " VALUES (%s, 'pool_buyer', %s, %s, 1)",
                (token_id, buyer_id, b'stand-in'),
            )
        conn.execute(
            'INSERT INTO pool_buyers (id, slug, environment, status, vault_token_id)'
            ' VALUES (%s, %s, %s, %s, %s)',
            (buyer_id, slug, environment, status, token_id),
        )
        ids[slug] = buyer_id
    return ids


async def _trip(make_member: MakeMember, conn: Conn) -> uuid.UUID:
    """Insert a trip organised by a fresh member and return its id."""
    account, _ = await make_member('Organiser')
    trip_id = uuid.uuid4()
    conn.execute(
        'INSERT INTO trips (id, name, organiser_account_id) VALUES (%s, %s, %s)',
        (trip_id, 'Spike trip', account.id),
    )
    return trip_id


async def test_lease_buyers_returns_the_requested_number_of_enrolled_buyers(
    db: AsyncSession, make_member: MakeMember, sync_conn: Conn
) -> None:
    from trippilot.payments import pool

    _seed_buyers(sync_conn, ['maya', 'sam', 'ana', 'leo'])
    trip = await _trip(make_member, sync_conn)

    leased = await pool.lease_buyers(db, trip, 3)
    await db.commit()

    assert [buyer.slug for buyer in leased] == ['ana', 'leo', 'maya']
    assert all(buyer.vault_token_id is not None for buyer in leased)
    assert _scalar(sync_conn, 'SELECT count(*) FROM buyer_leases WHERE trip_id = %s', (trip,)) == 3


async def test_a_second_trip_gets_only_the_buyers_left_and_never_one_already_leased(
    db: AsyncSession, make_member: MakeMember, sync_conn: Conn
) -> None:
    from trippilot.payments import pool

    _seed_buyers(sync_conn, ['maya', 'sam', 'ana', 'leo'])
    first_trip = await _trip(make_member, sync_conn)
    second_trip = await _trip(make_member, sync_conn)

    first = await pool.lease_buyers(db, first_trip, 3)
    await db.commit()
    second = await pool.lease_buyers(db, second_trip, 3)
    await db.commit()

    assert len(first) == 3
    assert len(second) == 1
    assert {b.slug for b in first}.isdisjoint({b.slug for b in second})
    assert await pool.lease_buyers(db, second_trip, 2) == []


async def test_two_concurrent_leases_never_share_a_buyer(
    db: AsyncSession, make_member: MakeMember, sync_conn: Conn
) -> None:
    from trippilot.db.engine import session_factory
    from trippilot.payments import pool

    _seed_buyers(sync_conn, ['maya', 'sam', 'ana', 'leo'])
    first_trip = await _trip(make_member, sync_conn)
    second_trip = await _trip(make_member, sync_conn)
    first_locked = asyncio.Event()
    second_done = asyncio.Event()

    async def first() -> list[str]:
        async with session_factory() as session:
            leased = await pool.lease_buyers(session, first_trip, 3)
            first_locked.set()
            await asyncio.wait_for(second_done.wait(), timeout=20)  # hold the row locks open
            await session.commit()
            return [buyer.slug for buyer in leased]

    async def second() -> list[str]:
        await asyncio.wait_for(first_locked.wait(), timeout=20)
        async with session_factory() as session:
            leased = await pool.lease_buyers(session, second_trip, 3)
            await session.commit()
            second_done.set()
            return [buyer.slug for buyer in leased]

    one, two = await asyncio.gather(first(), second())

    assert len(one) == 3
    assert len(two) == 1
    assert set(one).isdisjoint(two)
    assert _scalar(sync_conn, 'SELECT count(*) FROM buyer_leases WHERE released_at IS NULL') == 4


async def test_pending_and_retired_buyers_are_never_leased(
    db: AsyncSession, make_member: MakeMember, sync_conn: Conn
) -> None:
    from trippilot.payments import pool

    _seed_buyers(sync_conn, ['maya'])
    _seed_buyers(sync_conn, ['sam'], status='pending')
    _seed_buyers(sync_conn, ['ana'], status='retired')
    trip = await _trip(make_member, sync_conn)

    leased = await pool.lease_buyers(db, trip, 3)

    assert [buyer.slug for buyer in leased] == ['maya']


async def test_a_released_lease_makes_the_buyer_available_again(
    db: AsyncSession, make_member: MakeMember, sync_conn: Conn
) -> None:
    from trippilot.payments import pool

    _seed_buyers(sync_conn, ['maya'])
    first_trip = await _trip(make_member, sync_conn)
    second_trip = await _trip(make_member, sync_conn)
    (held,) = await pool.lease_buyers(db, first_trip, 1)
    await db.commit()
    assert await pool.lease_buyers(db, second_trip, 1) == []

    await pool.release_lease(db, held.lease_id)
    await db.commit()
    (again,) = await pool.lease_buyers(db, second_trip, 1)

    assert again.slug == 'maya'
    assert again.lease_id != held.lease_id
    assert (
        _scalar(
            sync_conn,
            'SELECT released_at IS NOT NULL FROM buyer_leases WHERE id = %s',
            (held.lease_id,),
        )
        is True
    )


async def test_an_expired_lease_no_longer_blocks_the_buyer(
    db: AsyncSession, make_member: MakeMember, sync_conn: Conn
) -> None:
    from trippilot.payments import pool

    _seed_buyers(sync_conn, ['maya'])
    first_trip = await _trip(make_member, sync_conn)
    second_trip = await _trip(make_member, sync_conn)
    await pool.lease_buyers(db, first_trip, 1, ttl=timedelta(seconds=-1))
    await db.commit()

    (again,) = await pool.lease_buyers(db, second_trip, 1)

    assert again.slug == 'maya'


async def test_releasing_an_unknown_or_already_released_lease_is_a_quiet_no_op(
    db: AsyncSession, make_member: MakeMember, sync_conn: Conn
) -> None:
    from trippilot.payments import pool

    _seed_buyers(sync_conn, ['maya'])
    trip = await _trip(make_member, sync_conn)
    (held,) = await pool.lease_buyers(db, trip, 1)

    await pool.release_lease(db, held.lease_id)
    await pool.release_lease(db, held.lease_id)
    await pool.release_lease(db, uuid.uuid4())
    await db.commit()

    assert (
        _scalar(sync_conn, 'SELECT count(*) FROM buyer_leases WHERE released_at IS NOT NULL') == 1
    )

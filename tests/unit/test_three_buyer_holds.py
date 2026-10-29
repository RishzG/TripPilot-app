"""The three-buyer hold spike (plan 01-14, D-35, D-36), against FakePayPal and the test database.

`ledger_entries` rows persist across tests (01-19), so every test uses its own run id and looks
its rows up by the `spike3-<run id>-` request id prefix; totals are never counted.
"""

from __future__ import annotations

import importlib.util
import sys
import uuid
from pathlib import Path
from types import ModuleType
from typing import TYPE_CHECKING, Any

import psycopg
import pytest
from cryptography.fernet import Fernet
from pydantic import SecretStr

from trippilot.contracts.money import Cents
from trippilot.contracts.paypal import PayPalError, VaultedAuthorization
from trippilot.payments import pool
from trippilot.payments.fake import FakePayPal
from trippilot.payments.ledger import Actor
from trippilot.payments.vault_store import VaultStore
from trippilot.settings import Settings, get_settings

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

SCRIPT = Path(__file__).resolve().parents[2] / 'scripts' / 'spikes' / 'three_buyer_holds.py'
Conn = psycopg.Connection[tuple[object, ...]]
SANDBOX_API = 'https://api-m.sandbox.paypal.com'
PROTECTED = ('3HJ189595J804324R', '21G42554211627257')


@pytest.fixture(scope='module')
def script() -> ModuleType:
    """Load scripts/spikes/three_buyer_holds.py by path (scripts/ is not a package)."""
    spec = importlib.util.spec_from_file_location('three_buyer_holds', SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules['three_buyer_holds'] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def run_id() -> str:
    """Return a run id no other test has used."""
    return f't{uuid.uuid4().hex[:12]}'


@pytest.fixture
def vault_key() -> str:
    """Return a fresh Fernet key for this test's vault."""
    return Fernet.generate_key().decode()


@pytest.fixture
def settings(vault_key: str) -> Settings:
    """Return sandbox, staging settings (copied, so no secret validation or .env is involved)."""
    return get_settings().model_copy(
        update={
            'app_env': 'staging',
            'paypal_mode': 'sandbox',
            'paypal_api_base': SANDBOX_API,
            'paypal_client_id': 'test-client-id-not-a-secret',
            'paypal_client_secret': SecretStr('test-secret-not-real'),
            'vault_keys': SecretStr(vault_key),
        }
    )


@pytest.fixture
def fake() -> FakePayPal:
    """Return the fake PayPal the run talks to."""
    return FakePayPal()


async def _enrol(
    db: AsyncSession, store: VaultStore, fake: FakePayPal, slug: str, environment: str = 'staging'
) -> None:
    """Add a pool buyer and enrol it the way the admin page does, against FakePayPal."""
    buyer = await pool.add_pool_buyer(
        db, slug, slug, f'sb-{slug}@personal.example.com', environment
    )
    setup = await fake.create_setup_token(request_id=f'set-{slug}', return_url='r', cancel_url='c')
    token = await fake.create_payment_token(request_id=f'pt-{slug}', setup_token_id=setup.id)
    saved = await store.save(db, 'pool_buyer', buyer.id, token, Actor(kind='system', id='test'))
    await pool.mark_enrolled(db, slug, saved.vault_token_id)
    await db.commit()


@pytest.fixture
async def enrolled(db: AsyncSession, vault_key: str, fake: FakePayPal) -> VaultStore:
    """Enrol maya, sam and ana on staging and return the store that holds their tokens."""
    store = VaultStore([vault_key])
    for slug in ('ana', 'sam', 'maya'):
        await _enrol(db, store, fake, slug)
    return store


def _as_dict(value: object) -> dict[str, Any]:
    """Narrow a psycopg jsonb cell to a dict."""
    assert isinstance(value, dict)
    return {str(key): item for key, item in value.items()}


def _as_cents(value: object) -> int | None:
    """Narrow a psycopg bigint cell to an int or None."""
    assert value is None or isinstance(value, int)
    return value


def _rows(
    conn: Conn, run: str
) -> list[tuple[str, str, dict[str, Any], int | None, dict[str, Any]]]:
    """Return (action, request id, paypal ids, cents, detail) of the run's rows, oldest first."""
    found = conn.execute(
        'SELECT action, request_id, paypal_ids, amount_cents, detail FROM ledger_entries'
        ' WHERE request_id LIKE %s ORDER BY id',
        (f'spike3-{run}-%',),
    ).fetchall()
    return [(str(a), str(r), _as_dict(p), _as_cents(c), _as_dict(d)) for a, r, p, c, d in found]


def _actions(rows: list[tuple[str, str, dict[str, Any], int | None, dict[str, Any]]]) -> list[str]:
    return [row[0] for row in rows]


def _count(fake: FakePayPal, method: str) -> int:
    return sum(1 for name, _ in fake.calls if name == method)


async def test_the_run_holds_three_captures_fifty_cents_of_maya_and_voids_the_rest(
    script: Any,
    run_id: str,
    settings: Settings,
    fake: FakePayPal,
    enrolled: VaultStore,
    sync_conn: Conn,
    capsys: pytest.CaptureFixture[str],
) -> None:
    code = await script.run_spike(run_id, settings=settings, gateway=fake)

    assert code == 0
    statuses = {state.id: state.status for state in fake.authorizations.values()}
    assert sorted(statuses.values()) == ['CAPTURED', 'VOIDED', 'VOIDED']
    assert _count(fake, 'create_order_authorize_vaulted') == 3
    assert _count(fake, 'capture_authorization') == 1
    assert _count(fake, 'void_authorization') == 2
    (capture_args,) = [args for name, args in fake.calls if name == 'capture_authorization']
    assert capture_args['amount'] == Cents(50)
    assert capture_args['final_capture'] is True
    assert all(
        args['amount'] == Cents(100)
        for name, args in fake.calls
        if name == 'create_order_authorize_vaulted'
    )

    rows = _rows(sync_conn, run_id)
    by_action = {action: [r for r in rows if r[0] == action] for action in _actions(rows)}
    assert {action: len(items) for action, items in by_action.items()} == {
        'vault.token_used': 3,
        'hold.placed': 3,
        'hold.captured': 1,
        'hold.voided': 2,
    }
    for _, req_id, paypal_ids, cents, detail in by_action['hold.placed']:
        assert req_id.endswith('-hold')
        assert paypal_ids['authorization_id'] in statuses
        assert cents == 100
        assert detail['status'] == 'CREATED'
        assert detail['expiration_time']
    (_, capture_req, capture_ids, capture_cents, capture_detail) = by_action['hold.captured'][0]
    assert capture_req == f'spike3-{run_id}-maya-capture'
    assert statuses[capture_ids['authorization_id']] == 'CAPTURED'
    assert capture_cents == 50
    assert capture_detail['status'] == 'CAPTURED'
    assert capture_detail['expiration_time']
    assert fake.authorizations[capture_ids['authorization_id']].captured == 50
    assert {r[1] for r in by_action['hold.voided']} == {
        f'spike3-{run_id}-sam-void',
        f'spike3-{run_id}-ana-void',
    }
    for _, _, ids, _, detail in by_action['hold.voided']:
        assert statuses[ids['authorization_id']] == 'VOIDED'
        assert detail['status'] == 'VOIDED'
    assert {r[1] for r in by_action['vault.token_used']} == {
        f'spike3-{run_id}-{slug}-hold' for slug in ('maya', 'sam', 'ana')
    }
    assert all(r[4]['purpose'] == 'spike hold' for r in by_action['vault.token_used'])

    out = capsys.readouterr()
    for state in fake.authorizations.values():
        assert state.id in out.out
    assert 'CAPTURED' in out.out
    assert out.out.count('VOIDED') >= 2


async def test_no_token_or_customer_id_is_ever_printed_or_ledgered(
    script: Any,
    run_id: str,
    settings: Settings,
    fake: FakePayPal,
    enrolled: VaultStore,
    sync_conn: Conn,
    capsys: pytest.CaptureFixture[str],
) -> None:
    await script.run_spike(run_id, settings=settings, gateway=fake)
    await script.report(run_id)

    shown = capsys.readouterr()
    ledger = repr(_rows(sync_conn, run_id))
    for token in fake.payment_tokens.values():
        for secret in (token.id, token.customer_id or ''):
            assert secret not in shown.out + shown.err
            assert secret not in ledger
    assert 'test-secret-not-real' not in shown.out + shown.err


async def test_re_running_the_same_run_id_creates_nothing_new(
    script: Any,
    run_id: str,
    settings: Settings,
    fake: FakePayPal,
    enrolled: VaultStore,
    sync_conn: Conn,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert await script.run_spike(run_id, settings=settings, gateway=fake) == 0
    first_rows = _rows(sync_conn, run_id)
    first_calls = len(fake.calls)
    capsys.readouterr()

    again = await script.run_spike(run_id, settings=settings, gateway=fake)

    assert again == 0
    assert _rows(sync_conn, run_id) == first_rows  # no second hold, token use, capture or void
    mutating = ('create_order_authorize_vaulted', 'capture_authorization', 'void_authorization')
    assert [_count(fake, m) for m in mutating] == [3, 1, 2]
    assert len(fake.authorizations) == 3
    # only the closing read-only status checks ran again
    assert {name for name, _ in fake.calls[first_calls:]} <= {'get_authorization'}
    assert 'skipped' in capsys.readouterr().out


async def test_a_run_that_fails_resumes_under_the_same_run_id_without_duplicates(
    script: Any,
    run_id: str,
    settings: Settings,
    fake: FakePayPal,
    enrolled: VaultStore,
    sync_conn: Conn,
    capsys: pytest.CaptureFixture[str],
) -> None:
    fake.fail_next('create_order_authorize_vaulted', PayPalError(500, 'INTERNAL_SERVER_ERROR'))

    first = await script.run_spike(run_id, settings=settings, gateway=fake)

    assert first == 1
    assert 'run_id' not in capsys.readouterr().out
    failed_rows = _rows(sync_conn, run_id)
    assert 'hold.failed' in _actions(failed_rows)
    assert 'hold.placed' not in _actions(failed_rows)
    assert fake.authorizations == {}

    resumed = await script.run_spike(run_id, settings=settings, gateway=fake)

    assert resumed == 0
    actions = _actions(_rows(sync_conn, run_id))
    assert actions.count('hold.placed') == 3
    assert actions.count('hold.failed') == 1
    assert len(fake.authorizations) == 3
    assert sorted(s.status for s in fake.authorizations.values()) == [
        'CAPTURED',
        'VOIDED',
        'VOIDED',
    ]


@pytest.mark.parametrize(
    ('update', 'message'),
    [
        ({'paypal_mode': 'fake'}, 'PAYPAL_MODE'),
        ({'paypal_api_base': 'https://api-m.paypal.com'}, 'sandbox host'),
        ({'paypal_api_base': 'https://api-m.sandbox.paypal.com.evil.example'}, 'sandbox host'),
        ({'app_env': 'production'}, 'production'),
        ({'paypal_client_id': ''}, 'PAYPAL_CLIENT_ID'),
    ],
)
async def test_it_refuses_to_run_outside_the_sandbox_or_on_production(
    script: Any,
    run_id: str,
    settings: Settings,
    fake: FakePayPal,
    enrolled: VaultStore,
    sync_conn: Conn,
    capsys: pytest.CaptureFixture[str],
    update: dict[str, Any],
    message: str,
) -> None:
    calls_before = len(fake.calls)

    code = await script.run_spike(run_id, settings=settings.model_copy(update=update), gateway=fake)

    assert code == 2
    assert message in capsys.readouterr().err
    assert len(fake.calls) == calls_before
    assert _rows(sync_conn, run_id) == []


async def test_it_refuses_when_fewer_than_three_buyers_are_enrolled(
    script: Any,
    run_id: str,
    settings: Settings,
    fake: FakePayPal,
    vault_key: str,
    db: AsyncSession,
    sync_conn: Conn,
    capsys: pytest.CaptureFixture[str],
) -> None:
    store = VaultStore([vault_key])
    await _enrol(db, store, fake, 'maya')
    await _enrol(db, store, fake, 'sam')
    await pool.add_pool_buyer(db, 'ana', 'ana', None, 'staging')  # pending, never enrolled
    await db.commit()
    calls_before = len(fake.calls)

    code = await script.run_spike(run_id, settings=settings, gateway=fake)

    assert code == 2
    assert 'found 2' in capsys.readouterr().err
    assert len(fake.calls) == calls_before
    assert _rows(sync_conn, run_id) == []


async def test_buyers_of_another_environment_are_ignored(
    script: Any,
    run_id: str,
    settings: Settings,
    fake: FakePayPal,
    vault_key: str,
    db: AsyncSession,
    capsys: pytest.CaptureFixture[str],
) -> None:
    store = VaultStore([vault_key])
    for slug in ('maya', 'sam', 'ana'):
        await _enrol(db, store, fake, slug, environment='production')

    code = await script.run_spike(run_id, settings=settings, gateway=fake)

    assert code == 2
    assert 'found 0' in capsys.readouterr().err


async def test_it_never_acts_on_one_of_the_open_01_18_holds(
    script: Any,
    run_id: str,
    settings: Settings,
    enrolled: VaultStore,
    sync_conn: Conn,
    capsys: pytest.CaptureFixture[str],
) -> None:
    class ReturnsAProtectedHold(FakePayPal):
        """A gateway whose hold comes back as one of the two open test holds."""

        async def create_order_authorize_vaulted(
            self, *, request_id: str, payment_token_id: str, amount: Cents, description: str
        ) -> VaultedAuthorization:
            return VaultedAuthorization('ORDER-X', PROTECTED[0], 'CREATED')

    gateway = ReturnsAProtectedHold()

    code = await script.run_spike(run_id, settings=settings, gateway=gateway)

    assert code == 1
    assert 'open 01-18 test hold' in capsys.readouterr().err
    assert not [n for n, _ in gateway.calls if n in ('capture_authorization', 'void_authorization')]
    assert 'hold.placed' not in _actions(_rows(sync_conn, run_id))


async def test_the_report_lists_the_run_and_only_the_webhooks_since_it_started(
    script: Any,
    run_id: str,
    settings: Settings,
    fake: FakePayPal,
    enrolled: VaultStore,
    sync_conn: Conn,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert await script.run_spike(run_id, settings=settings, gateway=fake) == 0
    (placed,) = [
        r for r in _rows(sync_conn, run_id) if r[0] == 'hold.placed' and r[1].endswith('maya-hold')
    ]
    maya_auth = placed[2]['authorization_id']
    tag = uuid.uuid4().hex[:8]
    sync_conn.execute(
        'INSERT INTO webhook_events (event_id, event_type, resource_id, verification_status)'
        " VALUES (%s, 'PAYMENT.CAPTURE.COMPLETED', %s, 'SUCCESS')",
        (f'WH-new-{tag}', maya_auth),
    )
    sync_conn.execute(
        'INSERT INTO webhook_events (event_id, event_type, resource_id, verification_status,'
        " received_at) VALUES (%s, 'PAYMENT.AUTHORIZATION.VOIDED', 'OLD-AUTH', 'SUCCESS',"
        " now() - interval '1 day')",
        (f'WH-old-{tag}',),
    )
    capsys.readouterr()

    code = await script.report(run_id)

    out = capsys.readouterr().out
    assert code == 0
    for state in fake.authorizations.values():
        assert state.id in out
    assert 'final statuses: CAPTURED, VOIDED, VOIDED -> OK' in out
    assert 'hold.placed' in out
    assert 'hold.captured' in out
    assert 'hold.voided' in out
    assert 'PAYMENT.CAPTURE.COMPLETED' in out
    assert 'OLD-AUTH' not in out
    assert 'verified events on this run' in out


async def test_the_report_is_read_only(
    script: Any,
    run_id: str,
    settings: Settings,
    fake: FakePayPal,
    enrolled: VaultStore,
    sync_conn: Conn,
) -> None:
    assert await script.run_spike(run_id, settings=settings, gateway=fake) == 0
    before = _rows(sync_conn, run_id)
    all_before = sync_conn.execute('SELECT count(*) FROM ledger_entries').fetchone()

    await script.report(run_id)

    assert _rows(sync_conn, run_id) == before
    assert sync_conn.execute('SELECT count(*) FROM ledger_entries').fetchone() == all_before


async def test_the_report_for_an_unknown_run_says_so_and_fails(
    script: Any, run_id: str, db: AsyncSession, capsys: pytest.CaptureFixture[str]
) -> None:
    code = await script.report(run_id)

    assert code == 1
    assert 'no ledger rows' in capsys.readouterr().out


def test_a_malformed_run_id_is_rejected_before_anything_runs(
    script: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    for bad in ('', 'has space', "x'; drop", 'a_b', 'x' * 41, '-lead'):
        assert script.main([f'--run-id={bad}']) == 2
    assert '--run-id' in capsys.readouterr().err


def test_the_script_reads_settings_from_the_environment_not_an_env_file() -> None:
    source = SCRIPT.read_text(encoding='utf-8')

    assert 'get_settings()' in source
    assert '_env_file' not in source
    assert 'load_env_file' not in source


def test_describe_payment_token_reports_ownership_facts_without_ids(script: Any) -> None:
    """The diagnose summary says whether PayPal returned a customer and the expected payer."""
    body = {
        'id': 'TOKEN-SECRET-ID',
        'customer': {'id': 'CUSTOMER-SECRET-ID'},
        'payment_source': {'paypal': {'email_address': 'Buyer@Example.com', 'payer_id': 'P1'}},
    }

    summary = script.describe_payment_token(body, 'buyer@example.com')

    assert summary == 'readable, customer present, payer email matches'
    assert 'TOKEN-SECRET-ID' not in summary
    assert 'CUSTOMER-SECRET-ID' not in summary
    mismatch = script.describe_payment_token({'payment_source': {'paypal': {}}}, 'b@example.com')
    assert mismatch == 'readable, customer missing, payer email differs'


async def test_diagnose_refuses_outside_the_sandbox(script: Any) -> None:
    """Diagnose makes no call unless it runs against the PayPal sandbox."""
    settings = get_settings().model_copy(update={'paypal_mode': 'fake'})

    assert await script.diagnose(settings=settings) == 2

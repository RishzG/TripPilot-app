"""PayPal webhook inbox through the API (plan 01-13, T-01-37 and T-01-38), FakePayPal only.

The procrastinate connector is replaced with the in-memory one, so deferred jobs are inspected
without a worker. `ledger_entries` rows persist across tests (01-19): ledger assertions filter on
this test's unique event id.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator, Mapping
from typing import TYPE_CHECKING

import httpx
import psycopg
import pytest
from fastapi import FastAPI
from procrastinate.testing import InMemoryConnector

from trippilot.app import create_app
from trippilot.jobs.app import app as jobs_app
from trippilot.payments import get_paypal_gateway
from trippilot.payments.fake import FakePayPal
from trippilot.payments.tasks import process_webhook_event
from trippilot.settings import get_settings

if TYPE_CHECKING:
    from conftest import MakeClient

Conn = psycopg.Connection[tuple[object, ...]]
WEBHOOK_ID = 'WH-TEST-ENVIRONMENT'
PATH = '/api/paypal/webhooks'
TASK_NAME = 'payments.process_webhook_event'
SIGNATURE_HEADERS = {
    'paypal-transmission-id': 'transmission-1',
    'paypal-transmission-time': '2026-10-29T12:00:00Z',
    'paypal-transmission-sig': 'c2lnbmF0dXJl',
    'paypal-cert-url': 'https://api.sandbox.paypal.com/v1/notifications/certs/CERT-1',
    'paypal-auth-algo': 'SHA256withRSA',
}


class RecordingPayPal(FakePayPal):
    """A FakePayPal that also remembers the headers each verification received."""

    def __init__(self) -> None:
        """Create the fake with no recorded headers."""
        super().__init__()
        self.verified_headers: list[dict[str, str]] = []

    async def verify_webhook_signature(
        self, *, headers: Mapping[str, str], raw_body: bytes, webhook_id: str
    ) -> bool:
        """Record the headers, then answer with the configured verdict."""
        self.verified_headers.append(dict(headers))
        return await super().verify_webhook_signature(
            headers=headers, raw_body=raw_body, webhook_id=webhook_id
        )


@pytest.fixture
def fake() -> RecordingPayPal:
    """Return the fake PayPal every request in a test talks to."""
    return RecordingPayPal()


@pytest.fixture
def queue() -> Iterator[InMemoryConnector]:
    """Swap the job queue for the in-memory connector so deferred jobs can be read back."""
    connector = InMemoryConnector()
    with jobs_app.replace_connector(connector):
        yield connector


def _build_app(fake: FakePayPal, webhook_id: str) -> FastAPI:
    settings = get_settings().model_copy(update={'paypal_webhook_id': webhook_id})
    built = create_app(settings)
    built.dependency_overrides[get_paypal_gateway] = lambda: fake
    return built


@pytest.fixture
def app(fake: RecordingPayPal, queue: InMemoryConnector) -> FastAPI:
    """Return an app whose environment has a webhook id and a FakePayPal."""
    return _build_app(fake, WEBHOOK_ID)


def _event(
    *,
    event_id: str | None = None,
    event_type: str = 'PAYMENT.AUTHORIZATION.CREATED',
    resource_id: str | None = None,
    status: str = 'CREATED',
) -> tuple[bytes, str, str]:
    """Return (raw body, event id, resource id) with deliberately unusual whitespace and order."""
    event_id = event_id or f'WH-EVT-{uuid.uuid4().hex}'
    resource_id = resource_id or f'AUTH-{uuid.uuid4().hex}'
    raw = (
        '{ "resource":  {"status":"' + status + '", "id": "' + resource_id + '"},\n'
        '  "id" : "' + event_id + '", "event_type":"' + event_type + '",'
        ' "resource_type":"authorization" }'
    ).encode()
    return raw, event_id, resource_id


async def _deliver(
    http: httpx.AsyncClient, raw: bytes, headers: dict[str, str] | None = None
) -> httpx.Response:
    return await http.post(
        PATH,
        content=raw,
        headers=SIGNATURE_HEADERS if headers is None else headers,
    )


def _rows(conn: Conn, event_id: str) -> list[tuple[object, ...]]:
    return conn.execute(
        'SELECT verification_status, event_type, resource_type, resource_id'
        ' FROM webhook_events WHERE event_id = %s',
        (event_id,),
    ).fetchall()


def _count_rows(conn: Conn) -> int:
    row = conn.execute('SELECT count(*) FROM webhook_events').fetchone()
    assert row is not None
    count = row[0]
    assert isinstance(count, int)
    return count


async def test_a_verified_delivery_is_stored_once_and_defers_one_job(
    app: FastAPI,
    make_client: MakeClient,
    queue: InMemoryConnector,
    sync_conn: Conn,
) -> None:
    raw, event_id, resource_id = _event()
    http = make_client(app)

    response = await _deliver(http, raw)

    assert response.status_code == 200
    assert _rows(sync_conn, event_id) == [
        ('SUCCESS', 'PAYMENT.AUTHORIZATION.CREATED', 'authorization', resource_id)
    ]
    assert [job['task_name'] for job in queue.jobs.values()] == [TASK_NAME]
    stored = sync_conn.execute(
        'SELECT id FROM webhook_events WHERE event_id = %s', (event_id,)
    ).fetchone()
    assert stored is not None
    assert [job['args'] for job in queue.jobs.values()] == [{'webhook_event_id': str(stored[0])}]


async def test_a_redelivered_event_id_stores_nothing_new_and_defers_nothing(
    app: FastAPI,
    make_client: MakeClient,
    queue: InMemoryConnector,
    sync_conn: Conn,
) -> None:
    raw, event_id, _ = _event()
    http = make_client(app)

    first = await _deliver(http, raw)
    second = await _deliver(http, raw)

    assert (first.status_code, second.status_code) == (200, 200)
    assert len(_rows(sync_conn, event_id)) == 1
    assert len(queue.jobs) == 1


async def test_an_unverified_delivery_answers_400_and_leaves_no_row_and_no_job(
    app: FastAPI,
    fake: RecordingPayPal,
    make_client: MakeClient,
    queue: InMemoryConnector,
    sync_conn: Conn,
) -> None:
    fake.webhook_verdict = False
    raw, event_id, _ = _event()
    http = make_client(app)

    response = await _deliver(http, raw)

    assert response.status_code == 400
    assert _rows(sync_conn, event_id) == []
    assert queue.jobs == {}


async def test_a_delivery_without_signature_headers_is_refused(
    app: FastAPI,
    fake: RecordingPayPal,
    make_client: MakeClient,
    queue: InMemoryConnector,
    sync_conn: Conn,
) -> None:
    fake.webhook_verdict = False  # the real client also answers False when a header is missing
    raw, event_id, _ = _event()
    http = make_client(app)

    response = await _deliver(http, raw, headers={})

    assert response.status_code == 400
    assert _rows(sync_conn, event_id) == []
    assert queue.jobs == {}


async def test_without_a_configured_webhook_id_the_endpoint_answers_503(
    fake: RecordingPayPal,
    queue: InMemoryConnector,
    make_client: MakeClient,
    sync_conn: Conn,
) -> None:
    app = _build_app(fake, '')
    raw, event_id, _ = _event()
    http = make_client(app)

    response = await _deliver(http, raw)

    assert response.status_code == 503
    assert fake.calls == []  # PayPal was never asked
    assert _rows(sync_conn, event_id) == []
    assert queue.jobs == {}


async def test_verification_receives_the_exact_posted_bytes_and_the_signature_headers(
    app: FastAPI, fake: RecordingPayPal, make_client: MakeClient
) -> None:
    raw, _, _ = _event()
    http = make_client(app)

    response = await _deliver(http, raw)

    assert response.status_code == 200
    verify_calls = [args for name, args in fake.calls if name == 'verify_webhook_signature']
    assert len(verify_calls) == 1
    assert verify_calls[0]['raw_body'] == raw
    assert verify_calls[0]['webhook_id'] == WEBHOOK_ID
    received = {key.lower(): value for key, value in fake.verified_headers[0].items()}
    for name, value in SIGNATURE_HEADERS.items():
        assert received[name] == value


async def test_an_unknown_event_type_is_stored_and_processed_like_any_other(
    app: FastAPI, make_client: MakeClient, queue: InMemoryConnector, sync_conn: Conn
) -> None:
    raw, event_id, _ = _event(event_type='SOMETHING.NEW.HAPPENED')
    http = make_client(app)

    response = await _deliver(http, raw)

    assert response.status_code == 200
    assert [row[1] for row in _rows(sync_conn, event_id)] == ['SOMETHING.NEW.HAPPENED']
    assert len(queue.jobs) == 1


async def test_a_verified_body_that_is_not_an_event_is_refused_without_a_row(
    app: FastAPI, make_client: MakeClient, queue: InMemoryConnector, sync_conn: Conn
) -> None:
    http = make_client(app)
    before = _count_rows(sync_conn)

    response = await _deliver(http, json.dumps(['not', 'an', 'event']).encode())

    assert response.status_code == 400
    assert _count_rows(sync_conn) == before
    assert queue.jobs == {}


async def test_the_webhook_path_is_exempt_from_the_origin_check(
    app: FastAPI, make_client: MakeClient
) -> None:
    raw, _, _ = _event()
    http = make_client(app)

    response = await _deliver(
        http, raw, headers={**SIGNATURE_HEADERS, 'origin': 'https://evil.example'}
    )

    assert response.status_code == 200


async def test_processing_marks_the_event_processed_and_writes_one_ledger_row(
    app: FastAPI, make_client: MakeClient, queue: InMemoryConnector, sync_conn: Conn
) -> None:
    raw, event_id, resource_id = _event(status='CAPTURED')
    http = make_client(app)
    assert (await _deliver(http, raw)).status_code == 200
    stored = sync_conn.execute(
        'SELECT id FROM webhook_events WHERE event_id = %s', (event_id,)
    ).fetchone()
    assert stored is not None
    job_args = next(iter(queue.jobs.values()))['args']

    await process_webhook_event(**job_args)
    await process_webhook_event(**job_args)  # a retried job must not double-record

    row = sync_conn.execute(
        'SELECT processed_at IS NOT NULL, summary FROM webhook_events WHERE event_id = %s',
        (event_id,),
    ).fetchone()
    assert row is not None
    assert row[0] is True
    assert row[1] == {'resource_id': resource_id, 'status': 'CAPTURED'}
    ledger = sync_conn.execute(
        'SELECT action, actor_kind, paypal_ids, detail FROM ledger_entries'
        " WHERE paypal_ids->>'event_id' = %s",
        (event_id,),
    ).fetchall()
    assert len(ledger) == 1
    action, actor_kind, paypal_ids, detail = ledger[0]
    assert (action, actor_kind) == ('webhook.received', 'system')
    assert paypal_ids == {'event_id': event_id, 'resource_id': resource_id}
    assert detail == {'event_type': 'PAYMENT.AUTHORIZATION.CREATED', 'status': 'CAPTURED'}

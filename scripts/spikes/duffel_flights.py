"""Duffel flights go/no-go spike (decision D-30), run through our own httpx adapter.

PASS bar: with a ``duffel_test_`` token, search, create a Duffel Airways (IATA ZZ) order paid
with ``balance``, read it back, then cancel it (create the cancellation and confirm it).
Anything less is NO-GO and VEND-05 leaves v1.

Safety properties:
- Test mode only: the script refuses to run unless the token starts with ``duffel_test_``.
- The token is read from settings as a ``SecretStr`` and never printed or logged. Error
  output uses ``DuffelError.summary()``, which carries only safe fields.
- Results go to ``scripts/spikes/results/duffel_flights.json`` (git-ignored).

Run: ``uv run python scripts/spikes/duffel_flights.py``
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx

from trippilot.settings import get_settings

JsonDict = dict[str, Any]

API_BASE = 'https://api.duffel.com'
DUFFEL_VERSION = 'v2'
TEST_TOKEN_PREFIX = 'duffel_test_'
DUFFEL_AIRWAYS_IATA = 'ZZ'
DAYS_OUT = 21
ROUTES = (('LHR', 'JFK'), ('JFK', 'LHR'), ('LHR', 'CDG'))
REPO_ROOT = Path(__file__).resolve().parents[2]
RESULTS_FILE = REPO_ROOT / 'scripts' / 'spikes' / 'results' / 'duffel_flights.json'
STEP_NAMES = {
    1: 'search offers',
    2: 'pick Duffel Airways offer and read it',
    3: 'create order paid with balance',
    4: 'read order back',
    5: 'cancel order (create and confirm cancellation)',
}
PASSENGER_IDENTITY: JsonDict = {
    'given_name': 'Trip',
    'family_name': 'Pilot',
    'born_on': '1990-01-01',
    'gender': 'm',
    'title': 'mr',
    'email': 'trippilot.spike@example.com',
    'phone_number': '+442080160509',
}


class DuffelError(Exception):
    """A Duffel API call returned an error status."""

    def __init__(self, status: int, errors: list[JsonDict]) -> None:
        self.status = status
        self.errors = errors
        first = errors[0] if errors else {}
        super().__init__(
            f'Duffel returned HTTP {status}: {first.get("code", "")} {first.get("message", "")}'.strip()
        )

    def summary(self) -> JsonDict:
        """Return only the safe parts of the error: status and per-error type, code, message."""
        return {
            'http_status': self.status,
            'errors': [
                {
                    'type': error.get('type'),
                    'code': error.get('code'),
                    'title': error.get('title'),
                    'message': error.get('message'),
                    'documentation_url': error.get('documentation_url'),
                }
                for error in self.errors
            ],
        }


class SpikeLog:
    """Collects one outcome per step and prints a `[works]` or `[fails]` line for each."""

    def __init__(self) -> None:
        self.steps: list[JsonDict] = []

    def record(self, step: int, outcome: str, detail: JsonDict) -> None:
        """Append a step outcome (``works`` or ``fails``) and print it."""
        entry: JsonDict = {
            'step': step,
            'name': STEP_NAMES.get(step, 'cleanup'),
            'outcome': outcome,
            'at': _utc_now(),
            'detail': detail,
        }
        self.steps.append(entry)
        print(f'[{outcome}] step {step} {entry["name"]}: {json.dumps(detail, default=str)}')


def _utc_now() -> str:
    """Return the current UTC time as an ISO-8601 string with a Z suffix."""
    return datetime.now(UTC).strftime('%Y-%m-%dT%H:%M:%SZ')


def _headers(token: str) -> dict[str, str]:
    """Build the Duffel request headers; the token only ever lives in this dict."""
    return {
        'Authorization': f'Bearer {token}',
        'Duffel-Version': DUFFEL_VERSION,
        'Accept': 'application/json',
        'Content-Type': 'application/json',
    }


async def call(
    client: httpx.AsyncClient,
    method: str,
    path: str,
    body: JsonDict | None = None,
    params: dict[str, str] | None = None,
) -> JsonDict:
    """Send one Duffel request and return its ``data`` payload, raising DuffelError on errors."""
    payload = {'data': body} if body is not None else None
    response = await client.request(method, path, json=payload, params=params)
    try:
        parsed: JsonDict = response.json() if response.content else {}
    except json.JSONDecodeError:
        parsed = {}
    if response.status_code >= 400:
        raw_errors = parsed.get('errors', [])
        errors = (
            [e for e in raw_errors if isinstance(e, dict)] if isinstance(raw_errors, list) else []
        )
        if not errors:
            errors = [{'message': 'non-JSON or empty error body'}]
        raise DuffelError(response.status_code, errors)
    data = parsed.get('data', {})
    return data if isinstance(data, dict) else {'items': data}


def _pick_zz_offer(offers: list[JsonDict]) -> JsonDict | None:
    """Return the cheapest offer owned by Duffel Airways (IATA ZZ), or None."""
    zz_offers = [
        offer for offer in offers if offer.get('owner', {}).get('iata_code') == DUFFEL_AIRWAYS_IATA
    ]
    if not zz_offers:
        return None
    return min(zz_offers, key=lambda offer: float(offer['total_amount']))


async def run_spike(client: httpx.AsyncClient, log: SpikeLog) -> JsonDict:
    """Run the five D-30 steps; return verdict, failed_step, order_id and cancellation_id."""
    ids: JsonDict = {'order_id': None, 'cancellation_id': None}
    failed_step: int | None = None
    order_created = False
    try:
        # Step 1: search for one adult, one slice, at least 14 days out.
        departure = (date.today() + timedelta(days=DAYS_OUT)).isoformat()
        offer: JsonDict | None = None
        request_data: JsonDict = {}
        failed_step = 1
        for origin, destination in ROUTES:
            request_data = await call(
                client,
                'POST',
                '/air/offer_requests',
                {
                    'slices': [
                        {'origin': origin, 'destination': destination, 'departure_date': departure}
                    ],
                    'passengers': [{'type': 'adult'}],
                    'cabin_class': 'economy',
                },
                params={'return_offers': 'true'},
            )
            offers = request_data.get('offers', [])
            owners = sorted({o.get('owner', {}).get('iata_code') for o in offers})
            log.record(
                1,
                'works' if offers else 'fails',
                {
                    'route': f'{origin}-{destination}',
                    'departure_date': departure,
                    'offer_request_id': request_data.get('id'),
                    'offer_count': len(offers),
                    'owner_iata_codes': owners,
                },
            )
            if not offers:
                continue
            offer = _pick_zz_offer(offers)
            if offer is not None:
                break
        # Step 2: pick a Duffel Airways offer and read it back.
        failed_step = 2
        if offer is None:
            log.record(2, 'fails', {'reason': 'no Duffel Airways (ZZ) offer on any tried route'})
            return _verdict(ids, failed_step)
        offer_detail = await call(client, 'GET', f'/air/offers/{offer["id"]}')
        log.record(
            2,
            'works',
            {
                'offer_id': offer_detail.get('id'),
                'owner': offer_detail.get('owner', {}).get('iata_code'),
                'total_amount': offer_detail.get('total_amount'),
                'total_currency': offer_detail.get('total_currency'),
            },
        )
        # Step 3: instant order paid with balance, amount and currency from the offer.
        failed_step = 3
        offer_passengers = offer_detail.get('passengers') or request_data.get('passengers', [])
        passengers = [{'id': p['id'], **PASSENGER_IDENTITY} for p in offer_passengers]
        order = await call(
            client,
            'POST',
            '/air/orders',
            {
                'type': 'instant',
                'selected_offers': [offer_detail['id']],
                'passengers': passengers,
                'payments': [
                    {
                        'type': 'balance',
                        'amount': offer_detail['total_amount'],
                        'currency': offer_detail['total_currency'],
                    }
                ],
            },
        )
        ids['order_id'] = order.get('id')
        order_created = True
        log.record(
            3,
            'works',
            {
                'order_id': order.get('id'),
                'booking_reference': order.get('booking_reference'),
                'total_amount': order.get('total_amount'),
                'total_currency': order.get('total_currency'),
            },
        )
        # Step 4: read the order back and check it is the one we created.
        failed_step = 4
        read_back = await call(client, 'GET', f'/air/orders/{ids["order_id"]}')
        if read_back.get('id') != ids['order_id']:
            log.record(4, 'fails', {'reason': 'order id mismatch on read-back'})
            return _verdict(ids, failed_step)
        log.record(
            4,
            'works',
            {
                'order_id': read_back.get('id'),
                'booking_reference': read_back.get('booking_reference'),
            },
        )
        # Step 5: create the cancellation, then confirm it.
        failed_step = 5
        await _cancel(client, log, ids, step=5)
        return _verdict(ids, None)
    except DuffelError as error:
        log.record(failed_step or 0, 'fails', error.summary())
    except httpx.HTTPError as error:
        log.record(failed_step or 0, 'fails', {'transport_error': type(error).__name__})
    if order_created and ids['cancellation_id'] is None:
        await _cleanup(client, log, ids)
    return _verdict(ids, failed_step)


async def _cancel(client: httpx.AsyncClient, log: SpikeLog, ids: JsonDict, step: int) -> None:
    """Create and confirm a cancellation for ``ids['order_id']``, recording the outcome."""
    cancellation = await call(
        client, 'POST', '/air/order_cancellations', {'order_id': ids['order_id']}
    )
    ids['cancellation_id'] = cancellation.get('id')
    confirmed = await call(
        client, 'POST', f'/air/order_cancellations/{ids["cancellation_id"]}/actions/confirm'
    )
    log.record(
        step,
        'works',
        {
            'cancellation_id': confirmed.get('id'),
            'refund_amount': confirmed.get('refund_amount'),
            'refund_currency': confirmed.get('refund_currency'),
            'confirmed_at': confirmed.get('confirmed_at'),
        },
    )


async def _cleanup(client: httpx.AsyncClient, log: SpikeLog, ids: JsonDict) -> None:
    """Best-effort cancellation of an order created before a later step failed."""
    try:
        await _cancel(client, log, ids, step=0)
    except DuffelError as error:
        log.record(0, 'fails', {'cleanup': error.summary()})
    except httpx.HTTPError as error:
        log.record(0, 'fails', {'cleanup_transport_error': type(error).__name__})


def _verdict(ids: JsonDict, failed_step: int | None) -> JsonDict:
    """Build the verdict block: GO only when no step failed."""
    return {
        'verdict': 'GO' if failed_step is None else 'NO-GO',
        'decided_at': _utc_now(),
        'failed_step': failed_step,
        'order_id': ids['order_id'],
        'cancellation_id': ids['cancellation_id'],
    }


def write_results(log: SpikeLog, verdict: JsonDict) -> JsonDict:
    """Write the results file, keeping the first run time for the one-day time-box record."""
    first_run_at = _utc_now()
    if RESULTS_FILE.exists():
        try:
            previous = json.loads(RESULTS_FILE.read_text(encoding='utf-8'))
            first_run_at = str(previous.get('first_run_at', first_run_at))
        except json.JSONDecodeError:
            pass
    document: JsonDict = {'first_run_at': first_run_at, 'steps': log.steps, **verdict}
    RESULTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    RESULTS_FILE.write_text(json.dumps(document, indent=2, default=str) + '\n', encoding='utf-8')
    return document


async def main() -> int:
    """Run the spike, record the verdict, and print it as one block for the SUMMARY."""
    token = get_settings().duffel_access_token.get_secret_value()
    if not token.startswith(TEST_TOKEN_PREFIX):
        print(
            f'DUFFEL_ACCESS_TOKEN is missing or does not start with {TEST_TOKEN_PREFIX}; '
            'refusing to run (test mode only). Value not shown.',
            file=sys.stderr,
        )
        return 2
    log = SpikeLog()
    async with httpx.AsyncClient(
        base_url=API_BASE, headers=_headers(token), timeout=httpx.Timeout(60.0)
    ) as client:
        verdict = await run_spike(client, log)
    document = write_results(log, verdict)
    print('--- verdict block ---')
    for key in (
        'verdict',
        'decided_at',
        'failed_step',
        'order_id',
        'cancellation_id',
        'first_run_at',
    ):
        print(f'{key}: {document[key]}')
    print(f'[{"works" if verdict["verdict"] == "GO" else "fails"}] overall')
    return 0


if __name__ == '__main__':
    raise SystemExit(asyncio.run(main()))

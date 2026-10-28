"""Pay Later spike (decision D-31, half-day time-box) plus the Duffel Stays cut-off (D-34).

A small local page and three order endpoints let a human buyer approve a server-created
``intent=AUTHORIZE`` order through the PayPal JS SDK v6 Pay Later button. A CLI then takes a
partial capture with ``final_capture`` and records the verdicts. Everything goes through the
typed app client (``get_paypal_gateway()``); the PayPal secret never reaches the browser, only the
public client id does.

Subcommands:
- ``serve``: serve the page on http://localhost:8765 (bound to 127.0.0.1 only).
    GET /                      the SDK v6 page (Pay Later button only when eligible)
    POST /orders               create the $12.00 AUTHORIZE order, return ``{orderId}``
    POST /orders/{id}/authorize  authorize the approved order and save the authorization id
    POST /eligibility          the page reports what the SDK said about eligibility
- ``capture``: capture $6.00 with ``final_capture`` (remainder released), read the status back.
- ``void``: void the authorization when the capture was not reached, read the status back.
- ``record --verdict PASS|NO-GO --stays adopted|v2 --stays-detail TEXT``: write the verdicts,
  the decision time and the final authorization status, and print the block for the SUMMARY.

Safety properties:
- Exactly one order amount: $12.00 (Pay in 4 needs $10 to $2,000). Request ids are fixed per run
  (``spike-paylater-<step>-<run id>``), so a restart or rerun cannot create a second order or a
  second capture. The run id is saved in the results file.
- No spike authorization is left open: ``record`` refuses to finish while one is not CAPTURED
  or VOIDED, and refuses a PASS unless the final status is CAPTURED.
- Sandbox only: refuses to run unless ``PAYPAL_MODE=sandbox`` and the API base is a sandbox host.
- Errors are reported through ``PayPalError.summary()``; the secret, tokens and buyer data are
  never printed or written.
- Results go to ``scripts/spikes/results/pay_later.json`` (git-ignored).

Run: ``PAYPAL_MODE=sandbox uv run python scripts/spikes/pay_later.py serve``
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response

from trippilot.contracts.money import Cents, to_paypal_value
from trippilot.contracts.paypal import PayPalError
from trippilot.payments import aclose_paypal_gateway, get_paypal_gateway
from trippilot.settings import Settings, get_settings

JsonDict = dict[str, Any]

REPO_ROOT = Path(__file__).resolve().parents[2]
RESULTS_FILE = REPO_ROOT / 'scripts' / 'spikes' / 'results' / 'pay_later.json'
PAGE_FILE = Path(__file__).resolve().parent / 'pay_later_page.html'
HOST = '127.0.0.1'
PORT = 8765
BASE_URL = f'http://localhost:{PORT}'
ORDER_CENTS = Cents(1200)  # Pay in 4 needs $10 to $2,000, so the usual $1 test order is ineligible
CAPTURE_CENTS = Cents(600)
DESCRIPTION = 'TripPilot Pay Later spike'
CLIENT_ID_PLACEHOLDER = '__CLIENT_ID_JSON__'
AMOUNT_PLACEHOLDER = '__AMOUNT_JSON__'
FINAL_STATUSES = ('CAPTURED', 'VOIDED', 'NOT_CREATED')
CLOSED_STATUSES = ('CAPTURED', 'VOIDED')


def _now_iso() -> str:
    """Return the current UTC time as an ISO 8601 string."""
    return datetime.now(UTC).isoformat(timespec='seconds')


def _read_results() -> JsonDict:
    """Return the saved results, or an empty dict when there is no file yet."""
    if not RESULTS_FILE.exists():
        return {}
    loaded = json.loads(RESULTS_FILE.read_text(encoding='utf-8'))
    return loaded if isinstance(loaded, dict) else {}


def _write_results(results: JsonDict) -> None:
    """Persist the results file, creating its (git-ignored) directory when needed."""
    RESULTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    RESULTS_FILE.write_text(json.dumps(results, indent=2, sort_keys=True) + '\n', encoding='utf-8')


def _update_results(**changes: object) -> JsonDict:
    """Merge `changes` into the saved results, persist them and return the merged dict."""
    results = _read_results()
    results.update(changes)
    _write_results(results)
    return results


def _sandbox_problem(settings: Settings) -> str | None:
    """Return why this script must refuse to run with these settings, or None when it is fine."""
    if settings.paypal_mode != 'sandbox':
        return 'refusing to run: set PAYPAL_MODE=sandbox'
    if 'sandbox' not in settings.paypal_api_base:
        return 'refusing to run: PAYPAL_API_BASE is not a sandbox host'
    if not settings.paypal_client_id or not settings.paypal_client_secret.get_secret_value():
        return 'refusing to run: PAYPAL_CLIENT_ID / PAYPAL_CLIENT_SECRET are not set'
    return None


def _run_id() -> str:
    """Return the saved run id, creating and saving one the first time it is needed."""
    results = _read_results()
    existing = results.get('run_id')
    if isinstance(existing, str) and existing:
        return existing
    created = datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')
    _update_results(run_id=created, run_started_at=_now_iso())
    return created


def _request_id(step: str) -> str:
    """Return the fixed request id for `step` in this run (reused on any rerun)."""
    return f'spike-paylater-{step}-{_run_id()}'


def _render_page(settings: Settings) -> str:
    """Return the page with the public client id and the order amount injected as JSON strings."""
    html = PAGE_FILE.read_text(encoding='utf-8')
    return html.replace(CLIENT_ID_PLACEHOLDER, json.dumps(settings.paypal_client_id)).replace(
        AMOUNT_PLACEHOLDER, json.dumps(to_paypal_value(ORDER_CENTS))
    )


# -- serve -----------------------------------------------------------------------------------


def _error_response(step: str, error: PayPalError) -> JSONResponse:
    """Save the safe error summary for `step` and answer 502 with the same summary."""
    summary = error.summary()
    _update_results(last_error={'step': step, 'at': _now_iso(), **summary})
    print(f'[fails] {step}: {summary}', flush=True)
    return JSONResponse({'error': step, 'paypal': summary}, status_code=502)


def build_app(settings: Settings) -> FastAPI:
    """Build the local page server; the PayPal gateway is closed when the server stops."""

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        await aclose_paypal_gateway()

    app = FastAPI(title='TripPilot Pay Later spike', lifespan=lifespan)

    @app.get('/', response_class=HTMLResponse)
    async def page() -> str:
        """Serve the SDK v6 page."""
        return _render_page(settings)

    @app.post('/orders', response_model=None)
    async def create_order() -> Response:
        """Create the $12.00 AUTHORIZE order (a fixed request id makes a repeat idempotent)."""
        gateway = get_paypal_gateway()
        try:
            order = await gateway.create_order_authorize(
                request_id=_request_id('order'),
                amount=ORDER_CENTS,
                description=DESCRIPTION,
                return_url=f'{BASE_URL}/return',
                cancel_url=f'{BASE_URL}/cancel',
            )
        except PayPalError as error:
            return _error_response('create_order', error)
        _update_results(
            order_id=order.id,
            order_status=order.status,
            order_amount_cents=int(ORDER_CENTS),
            order_created_at=_now_iso(),
        )
        print(f'[works] create_order: {order.id} status={order.status}', flush=True)
        return JSONResponse({'orderId': order.id})

    @app.post('/orders/{order_id}/authorize', response_model=None)
    async def authorize(order_id: str) -> Response:
        """Authorize the approved order and save the authorization id."""
        saved = _read_results().get('order_id')
        if order_id != saved:
            print('[fails] authorize: order id is not the one this run created', flush=True)
            return JSONResponse({'error': 'unknown order'}, status_code=404)
        gateway = get_paypal_gateway()
        try:
            authorization = await gateway.authorize_order(
                request_id=_request_id('auth'), order_id=order_id
            )
        except PayPalError as error:
            return _error_response('authorize_order', error)
        _update_results(
            authorization_id=authorization.id,
            authorization_status=authorization.status,
            authorization_amount_cents=int(authorization.amount),
            authorized_at=_now_iso(),
            authorization_expiration_time=authorization.expiration_time,
        )
        print(f'[works] authorize_order: {authorization.id} status={authorization.status}')
        return JSONResponse({'authorizationId': authorization.id, 'status': authorization.status})

    @app.post('/eligibility', response_model=None)
    async def eligibility(request: Request) -> Response:
        """Save what the SDK reported about eligibility (evidence for a NO-GO)."""
        payload = await request.json()
        _update_results(eligibility={'reported_at': _now_iso(), 'sdk': payload})
        shown = payload.get('paylater') if isinstance(payload, dict) else None
        print(f'[works] eligibility reported by the page: paylater={shown}', flush=True)
        return JSONResponse({'saved': True})

    @app.get('/return', response_class=HTMLResponse)
    async def return_page() -> str:
        """Landing page for PayPal's return redirect (the popup flow normally does not use it)."""
        return '<p>Approved. You can close this tab and return to the spike page.</p>'

    @app.get('/cancel', response_class=HTMLResponse)
    async def cancel_page() -> str:
        """Landing page for PayPal's cancel redirect."""
        return '<p>Cancelled. You can close this tab and return to the spike page.</p>'

    return app


def cmd_serve(*, new_run: bool) -> int:
    """Run the local server until it is stopped with Ctrl+C."""
    settings = get_settings()
    problem = _sandbox_problem(settings)
    if problem is not None:
        print(problem, file=sys.stderr)
        return 2
    results = _read_results()
    if new_run:
        open_hold = results.get('authorization_id') and results.get('final_status') is None
        if open_hold:
            print('[fails] serve: refusing --new-run while a spike hold is open', file=sys.stderr)
            return 1
        _write_results({})
    run_id = _run_id()
    print(f'[works] serve: run {run_id}, results in {RESULTS_FILE.relative_to(REPO_ROOT)}')
    print(f'[works] serve: open {BASE_URL}/ in a desktop browser (Ctrl+C to stop)', flush=True)
    uvicorn.run(build_app(settings), host=HOST, port=PORT, log_level='warning')
    return 0


# -- capture and void ------------------------------------------------------------------------


async def cmd_capture() -> int:
    """Capture $6.00 with final_capture, then read the authorization status back."""
    settings = get_settings()
    problem = _sandbox_problem(settings)
    if problem is not None:
        print(problem, file=sys.stderr)
        return 2
    results = _read_results()
    authorization_id = results.get('authorization_id')
    if not isinstance(authorization_id, str) or not authorization_id:
        print(
            '[fails] capture: no authorization saved; the buyer has not approved', file=sys.stderr
        )
        return 1
    gateway = get_paypal_gateway()
    try:
        try:
            capture = await gateway.capture_authorization(
                request_id=_request_id('capture'),
                authorization_id=authorization_id,
                amount=CAPTURE_CENTS,
                final_capture=True,
            )
        except PayPalError as error:
            _update_results(last_error={'step': 'capture', 'at': _now_iso(), **error.summary()})
            print(f'[fails] capture: {error.summary()}')
            print('[fails] capture: run `void` so no spike hold stays open')
            return 1
        print(f'[works] capture: {capture.id} status={capture.status} cents={int(capture.amount)}')
        authorization = await gateway.get_authorization(authorization_id)
    except PayPalError as error:
        _update_results(last_error={'step': 'read_back', 'at': _now_iso(), **error.summary()})
        print(f'[fails] read authorization after capture: {error.summary()}')
        return 1
    finally:
        await aclose_paypal_gateway()
    _update_results(
        capture_id=capture.id,
        capture_status=capture.status,
        captured_cents=int(capture.amount),
        captured_at=_now_iso(),
        authorization_status=authorization.status,
        final_status=authorization.status,
    )
    print(f'[works] authorization {authorization_id} reads {authorization.status}')
    if authorization.status != 'CAPTURED':
        print('[fails] capture: authorization is not CAPTURED; consider `void`')
        return 1
    print('[works] remainder released by final_capture')
    return 0


async def cmd_void() -> int:
    """Void the authorization (when the capture was not reached) and read the status back."""
    settings = get_settings()
    problem = _sandbox_problem(settings)
    if problem is not None:
        print(problem, file=sys.stderr)
        return 2
    authorization_id = _read_results().get('authorization_id')
    if not isinstance(authorization_id, str) or not authorization_id:
        print('[works] void: no authorization was created; nothing to void')
        return 0
    gateway = get_paypal_gateway()
    try:
        authorization = await gateway.void_authorization(
            request_id=_request_id('void'), authorization_id=authorization_id
        )
    except PayPalError as error:
        _update_results(last_error={'step': 'void', 'at': _now_iso(), **error.summary()})
        print(f'[fails] void: {error.summary()}')
        return 1
    finally:
        await aclose_paypal_gateway()
    _update_results(
        authorization_status=authorization.status,
        final_status=authorization.status,
        voided_at=_now_iso(),
    )
    print(f'[works] authorization {authorization_id} reads {authorization.status}')
    return 0 if authorization.status in CLOSED_STATUSES else 1


# -- record ----------------------------------------------------------------------------------


def cmd_record(*, verdict: str, stays: str, stays_detail: str) -> int:
    """Write the D-31 verdict, the D-34 Stays outcome and the final status; print the block."""
    results = _read_results()
    authorization_id = results.get('authorization_id')
    final_status = results.get('final_status')
    if not isinstance(authorization_id, str) or not authorization_id:
        final_status = 'NOT_CREATED'
    elif final_status not in CLOSED_STATUSES:
        print(
            f'[fails] record: authorization {authorization_id} is not closed; run `capture` or '
            '`void` first so no spike hold stays open',
            file=sys.stderr,
        )
        return 1
    if verdict == 'PASS' and final_status != 'CAPTURED':
        print('[fails] record: PASS needs final_status CAPTURED (the D-31 bar)', file=sys.stderr)
        return 1
    results = _update_results(
        verdict=verdict,
        decided_at=_now_iso(),
        final_status=final_status,
        stays={'outcome': stays, 'detail': stays_detail, 'decided_at': _now_iso()},
    )
    block = {
        'verdict': results['verdict'],
        'decided_at': results['decided_at'],
        'authorization_id': results.get('authorization_id'),
        'captured_cents': results.get('captured_cents'),
        'final_status': results['final_status'],
        'eligibility_paylater': (results.get('eligibility') or {}).get('sdk', {}).get('paylater'),
        'stays': results['stays'],
    }
    print(f'[works] recorded in {RESULTS_FILE.relative_to(REPO_ROOT)}')
    print(json.dumps(block, indent=2, sort_keys=True))
    return 0


# -- entry point -----------------------------------------------------------------------------


def _parser() -> argparse.ArgumentParser:
    """Build the subcommand parser."""
    parser = argparse.ArgumentParser(description='Pay Later spike (D-31) and Stays cut-off (D-34).')
    sub = parser.add_subparsers(dest='command', required=True)
    serve = sub.add_parser('serve', help=f'serve the Pay Later page on {BASE_URL}')
    serve.add_argument(
        '--new-run',
        action='store_true',
        help='start a fresh run id and results file (refused while a hold is open)',
    )
    sub.add_parser('capture', help='capture $6.00 with final_capture and read the status back')
    sub.add_parser('void', help='void the authorization if the capture was not reached')
    record = sub.add_parser('record', help='write the verdicts and the final status')
    record.add_argument('--verdict', required=True, choices=('PASS', 'NO-GO'))
    record.add_argument('--stays', required=True, choices=('adopted', 'v2'))
    record.add_argument('--stays-detail', required=True, help='one-line reason for the outcome')
    return parser


def main(argv: list[str] | None = None) -> int:
    """Dispatch the chosen subcommand and return the process exit code."""
    args = _parser().parse_args(argv)
    if args.command == 'serve':
        return cmd_serve(new_run=args.new_run)
    if args.command == 'capture':
        return asyncio.run(cmd_capture())
    if args.command == 'void':
        return asyncio.run(cmd_void())
    return cmd_record(verdict=args.verdict, stays=args.stays, stays_detail=args.stays_detail)


if __name__ == '__main__':
    sys.exit(main())

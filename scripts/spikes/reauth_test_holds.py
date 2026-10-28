"""Reauthorize and close the two open test holds placed by plan 01-02 (plan 01-18, D-29).

Three commands, all driven through the typed gateway client with the staging app's credentials
(the app that created the holds, UD-1):

- ``inspect``: read-only. Prints each hold's PayPal status and its reauth window using only GETs.
- ``reauth --hold N``: refuses to run before that hold's ``reauth_not_before`` (exit 2). Otherwise
  reauthorizes the hold (step ``a``), reads back the returned authorization and the original id,
  then tries a second reauthorize on the newest id (step ``b``). Every outcome is recorded in
  ``scripts/spikes/results/reauth.json`` and steps already recorded are skipped on a re-run.
- ``close --hold N``: captures 0.50 USD with ``final_capture`` on the newest valid authorization,
  or voids it if the capture is refused, so no test hold is left open.

Safety properties:
- Sandbox only: refuses to run unless ``PAYPAL_MODE=sandbox`` and the API base is a sandbox host.
- Fixed ``PayPal-Request-Id`` values (``trippilot-spike-reauth-...``) make a repeated call return
  the original result instead of acting twice, and recorded steps are never repeated.
- Every reauth time comes from the hold's stored PayPal ``create_time`` in ``test_holds.json``;
  no calendar date is written in this script.
- Secrets are never printed; PayPal errors are reported through ``PayPalError.summary()``.

Run: ``PAYPAL_MODE=sandbox uv run python scripts/spikes/reauth_test_holds.py inspect``
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx

from trippilot.contracts.money import Cents
from trippilot.contracts.paypal import Authorization, PayPalError, PayPalGateway
from trippilot.payments.client import PayPalClient
from trippilot.settings import get_settings

JsonDict = dict[str, Any]

REPO_ROOT = Path(__file__).resolve().parents[2]
RESULTS_DIR = REPO_ROOT / 'scripts' / 'spikes' / 'results'
HOLDS_FILE = RESULTS_DIR / 'test_holds.json'
REAUTH_FILE = RESULTS_DIR / 'reauth.json'
REQUEST_ID_PREFIX = 'trippilot-spike-reauth'
CAPTURE_CENTS = Cents(50)
OPEN_STATUSES = frozenset({'CREATED', 'PENDING', 'PARTIALLY_CAPTURED'})
EXIT_REFUSED = 2


def parse_time(value: str) -> datetime:
    """Parse a PayPal ISO-8601 timestamp (trailing Z) into an aware UTC datetime."""
    return datetime.fromisoformat(value.replace('Z', '+00:00')).astimezone(UTC)


def now_utc() -> datetime:
    """Return the current time as an aware UTC datetime."""
    return datetime.now(UTC)


def iso_z(moment: datetime) -> str:
    """Format a datetime as an ISO-8601 UTC string with a trailing Z."""
    return moment.astimezone(UTC).strftime('%Y-%m-%dT%H:%M:%SZ')


def describe_wait(delta: timedelta) -> str:
    """Describe a timedelta as days, hours and minutes (or 'open now' when not positive)."""
    seconds = int(delta.total_seconds())
    if seconds <= 0:
        return 'open now'
    days, rest = divmod(seconds, 86400)
    hours, rest = divmod(rest, 3600)
    return f'{days}d {hours}h {rest // 60}m'


def load_holds() -> dict[int, JsonDict]:
    """Read the hold records written by plan 01-02, keyed by hold number."""
    raw: JsonDict = json.loads(HOLDS_FILE.read_text(encoding='utf-8'))
    return {int(hold['hold']): dict(hold) for hold in raw.get('holds', [])}


def load_results() -> JsonDict:
    """Read reauth.json, or an empty record when nothing has run yet."""
    if not REAUTH_FILE.exists():
        return {}
    loaded: JsonDict = json.loads(REAUTH_FILE.read_text(encoding='utf-8'))
    return loaded


def save_results(results: JsonDict) -> None:
    """Write the (git-ignored) results file; called after every step so a crash loses nothing."""
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    REAUTH_FILE.write_text(json.dumps(results, indent=2, sort_keys=True) + '\n', encoding='utf-8')


def authorization_record(auth: Authorization) -> JsonDict:
    """Return the PayPal-reported fields of an authorization for the results file."""
    return {
        'authorization_id': auth.id,
        'status': auth.status,
        'amount_cents': int(auth.amount),
        'create_time': auth.create_time,
        'expiration_time': auth.expiration_time,
    }


def request_id(number: int, suffix: str) -> str:
    """Build the fixed PayPal-Request-Id for one hold and step."""
    return f'{REQUEST_ID_PREFIX}-{number}-{suffix}'


def newest_authorization_id(hold: JsonDict, record: JsonDict) -> str:
    """Return the newest authorization id: step b, else step a, else the original id."""
    steps: JsonDict = record.get('steps', {})
    for key in ('b', 'a'):
        step = steps.get(key)
        if isinstance(step, dict) and step.get('ok') and step.get('authorization_id'):
            return str(step['authorization_id'])
    return str(hold['id'])


def known_authorization_ids(hold: JsonDict, record: JsonDict) -> list[str]:
    """Return every authorization id seen for a hold, oldest first, without duplicates."""
    ids = [str(hold['id'])]
    steps: JsonDict = record.get('steps', {})
    for key in ('a', 'b'):
        step = steps.get(key)
        if isinstance(step, dict) and step.get('ok') and step.get('authorization_id'):
            candidate = str(step['authorization_id'])
            if candidate not in ids:
                ids.append(candidate)
    return ids


def make_client(http: httpx.AsyncClient) -> PayPalGateway | None:
    """Build the sandbox client, or print why not and return None (never touches live)."""
    settings = get_settings()
    if settings.paypal_mode != 'sandbox':
        print('refusing to run: set PAYPAL_MODE=sandbox', file=sys.stderr)
        return None
    if 'sandbox' not in settings.paypal_api_base:
        print('refusing to run: PAYPAL_API_BASE is not a sandbox host', file=sys.stderr)
        return None
    if not settings.paypal_client_id or not settings.paypal_client_secret.get_secret_value():
        print(
            'refusing to run: PAYPAL_CLIENT_ID / PAYPAL_CLIENT_SECRET are not set',
            file=sys.stderr,
        )
        return None
    return PayPalClient(
        http,
        settings.paypal_api_base,
        settings.paypal_web_base,
        settings.paypal_client_id,
        settings.paypal_client_secret,
    )


async def run_inspect(client: PayPalGateway) -> int:
    """Print every hold's status and reauth window using only GETs; return an exit code."""
    holds = load_holds()
    results = load_results()
    printed = 0
    for number in sorted(holds):
        hold = holds[number]
        try:
            auth = await client.get_authorization(str(hold['id']))
        except PayPalError as error:
            print(f'[fails] hold {number}: {json.dumps(error.summary())}', file=sys.stderr)
            continue
        wait = describe_wait(parse_time(str(hold['reauth_not_before'])) - now_utc())
        recorded = results.get(f'hold_{number}', {})
        print(f'hold {number}: id={auth.id}')
        print(f'  status={auth.status} amount_cents={int(auth.amount)}')
        print(f'  create_time={auth.create_time} expiration_time={auth.expiration_time}')
        print(f'  honor_ends={hold["honor_ends"]} reauth_not_before={hold["reauth_not_before"]}')
        print(f'  reauth window: {wait}')
        if recorded:
            print(f'  recorded: steps={sorted(recorded.get("steps", {}))}')
            print(f'  recorded final_status={recorded.get("final_status")}')
        printed += 1
    return 0 if printed >= 2 else 1


async def read_back(client: PayPalGateway, authorization_id: str) -> JsonDict:
    """GET an authorization and return its record, or the safe error summary."""
    try:
        return {
            'readable': True,
            **authorization_record(await client.get_authorization(authorization_id)),
        }
    except PayPalError as error:
        return {'readable': False, 'error': error.summary()}


async def run_reauth(client: PayPalGateway, number: int) -> int:
    """Reauthorize one hold after its window opens, recording every outcome; return exit code."""
    holds = load_holds()
    hold = holds.get(number)
    if hold is None:
        print(f'no hold {number} in {HOLDS_FILE.name}', file=sys.stderr)
        return EXIT_REFUSED
    not_before = parse_time(str(hold['reauth_not_before']))
    remaining = not_before - now_utc()
    if remaining > timedelta(0):
        print(
            f'refusing: hold {number} may be reauthorized from {iso_z(not_before)} '
            f'({describe_wait(remaining)} to wait)',
            file=sys.stderr,
        )
        return EXIT_REFUSED

    results = load_results()
    record: JsonDict = results.setdefault(f'hold_{number}', {'steps': {}})
    record.setdefault('steps', {})
    steps: JsonDict = record['steps']
    original_id = str(hold['id'])

    try:
        if 'a' not in steps:
            try:
                first = await client.reauthorize(
                    request_id=request_id(number, 'a'), authorization_id=original_id, amount=None
                )
            except PayPalError as error:
                if error.status >= 500:
                    raise
                steps['a'] = {'ok': False, 'at': iso_z(now_utc()), 'error': error.summary()}
                save_results(results)
                print(f'[works] hold {number} step a refused: {json.dumps(error.summary())}')
            else:
                steps['a'] = {
                    'ok': True,
                    'at': iso_z(now_utc()),
                    'same_id_as_original': first.id == original_id,
                    **authorization_record(first),
                    'readback': await read_back(client, first.id),
                }
                save_results(results)
                print(f'[works] hold {number} step a: {json.dumps(steps["a"])}')
        else:
            print(f'hold {number} step a already recorded; skipping')

        if 'original_readable' not in record:
            record['original_readable'] = await read_back(client, original_id)
            save_results(results)
            print(f'hold {number} original id: {json.dumps(record["original_readable"])}')

        step_a = steps.get('a', {})
        if 'b' not in steps and step_a.get('ok'):
            newest = str(step_a['authorization_id'])
            try:
                second = await client.reauthorize(
                    request_id=request_id(number, 'b'), authorization_id=newest, amount=None
                )
            except PayPalError as error:
                if error.status >= 500:
                    raise
                steps['b'] = {'ok': False, 'at': iso_z(now_utc()), 'error': error.summary()}
                save_results(results)
                print(f'[works] hold {number} step b refused: {json.dumps(error.summary())}')
            else:
                steps['b'] = {
                    'ok': True,
                    'at': iso_z(now_utc()),
                    'same_id_as_previous': second.id == newest,
                    **authorization_record(second),
                    'readback': await read_back(client, second.id),
                }
                save_results(results)
                print(f'[works] hold {number} step b: {json.dumps(steps["b"])}')
        elif 'b' in steps:
            print(f'hold {number} step b already recorded; skipping')
    except PayPalError as error:
        print(f'[fails] PayPal call failed: {json.dumps(error.summary())}', file=sys.stderr)
        return 1
    except httpx.HTTPError as error:
        print(f'[fails] network error: {type(error).__name__}', file=sys.stderr)
        return 1
    return 0


async def run_close(client: PayPalGateway, number: int) -> int:
    """Capture 0.50 USD (final) on the newest valid authorization, or void it; return exit code."""
    holds = load_holds()
    hold = holds.get(number)
    results = load_results()
    record: JsonDict | None = results.get(f'hold_{number}')
    if hold is None or record is None or 'a' not in record.get('steps', {}):
        print(
            f'refusing: hold {number} has no recorded reauthorize outcome; run reauth first',
            file=sys.stderr,
        )
        return EXIT_REFUSED
    if record.get('final_status') in ('CAPTURED', 'VOIDED'):
        print(f'hold {number} already closed: {record["final_status"]}; making no PayPal calls')
        return 0

    target = newest_authorization_id(hold, record)
    try:
        try:
            capture = await client.capture_authorization(
                request_id=request_id(number, 'capture'),
                authorization_id=target,
                amount=CAPTURE_CENTS,
                final_capture=True,
            )
        except PayPalError as error:
            if error.status >= 500:
                raise
            record['capture'] = {'ok': False, 'error': error.summary()}
            save_results(results)
            print(f'hold {number} capture refused, voiding: {json.dumps(error.summary())}')
            voided = await client.void_authorization(
                request_id=request_id(number, 'void'), authorization_id=target
            )
            record['void'] = authorization_record(voided)
        else:
            record['capture'] = {
                'ok': True,
                'capture_id': capture.id,
                'status': capture.status,
                'amount_cents': int(capture.amount),
                'authorization_id': target,
            }
        save_results(results)

        final = await client.get_authorization(target)
        record['final_status'] = final.status
        record['final'] = authorization_record(final)
        save_results(results)

        # Any other id for this hold that is still open must be released too.
        others: JsonDict = {}
        for other in known_authorization_ids(hold, record):
            if other == target:
                continue
            state = await read_back(client, other)
            if state.get('status') in OPEN_STATUSES:
                released = await client.void_authorization(
                    request_id=request_id(number, f'void-{other[-6:]}'), authorization_id=other
                )
                state = {'readable': True, **authorization_record(released)}
            others[other] = state
        record['other_ids_after_close'] = others
        save_results(results)
    except PayPalError as error:
        print(f'[fails] PayPal call failed: {json.dumps(error.summary())}', file=sys.stderr)
        return 1
    except httpx.HTTPError as error:
        print(f'[fails] network error: {type(error).__name__}', file=sys.stderr)
        return 1

    print(f'[works] hold {number} closed: {record["final_status"]}')
    print(json.dumps(record, indent=2, sort_keys=True))
    return 0


async def run(args: argparse.Namespace) -> int:
    """Dispatch the chosen command with one shared sandbox client."""
    async with httpx.AsyncClient(timeout=30.0) as http:
        client = make_client(http)
        if client is None:
            return EXIT_REFUSED
        if args.command == 'inspect':
            return await run_inspect(client)
        if args.command == 'reauth':
            return await run_reauth(client, int(args.hold))
        return await run_close(client, int(args.hold))


def build_parser() -> argparse.ArgumentParser:
    """Build the command line parser for inspect, reauth and close."""
    parser = argparse.ArgumentParser(
        description=__doc__.split('\n', maxsplit=1)[0] if __doc__ else ''
    )
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('inspect', help='read-only status of both holds')
    for name, text in (('reauth', 'reauthorize one hold'), ('close', 'capture or void one hold')):
        command = sub.add_parser(name, help=text)
        command.add_argument('--hold', type=int, choices=(1, 2), required=True)
    return parser


def main() -> int:
    """Parse the command line and run the chosen command."""
    return asyncio.run(run(build_parser().parse_args()))


if __name__ == '__main__':
    sys.exit(main())

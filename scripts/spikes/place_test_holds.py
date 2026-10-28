"""Place the two open $1.00 reauthorization test holds on the vaulted sandbox buyer.

One-off, standard-library-only spike (decision D-29). It runs before the app scaffold
exists, so it must not import anything outside the standard library. Unlike the earlier
reference script it NEVER voids or captures a hold: the two holds stay open so they can
be reauthorized on day 4 and day 5 (plan 01-18).

Safety properties:
- Fixed ``PayPal-Request-Id`` values make a repeated POST return the same order.
- A results-file guard means a re-run never creates a third hold.
- Credentials and the vault token are read at runtime and never printed or logged.

Run: ``uv run --no-project python scripts/spikes/place_test_holds.py``
"""

from __future__ import annotations

import base64
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

JsonDict = dict[str, Any]

API_BASE = 'https://api-m.sandbox.paypal.com'
REPO_ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = REPO_ROOT / '.env'
VAULT_FILE = REPO_ROOT / 'vault_token.json'
RESULTS_FILE = REPO_ROOT / 'scripts' / 'spikes' / 'results' / 'test_holds.json'
APP_LABEL = 'staging (BAA8yyz5...)'
AMOUNT = '1.00'
HOLD_NUMBERS = (1, 2)
HONOR_HOURS = 72
# Hold 1 is reauthorized at the end of the honor period, hold 2 a day later.
REAUTH_HOURS = {1: HONOR_HOURS, 2: HONOR_HOURS + 24}
# Candidate key names for the vault payment token id (checked by name only, never printed).
VAULT_ID_KEYS = ('payment_token_id', 'vault_id', 'payment_token', 'id')


class PayPalError(Exception):
    """A PayPal API call returned an error status."""

    def __init__(self, status: int, body: JsonDict) -> None:
        self.status = status
        self.body = body
        name = body.get('name', body.get('error', ''))
        message = body.get('message', body.get('error_description', ''))
        super().__init__(f'PayPal returned HTTP {status}: {name} {message}'.strip())

    def summary(self) -> JsonDict:
        """Return only the safe parts of the error: status, name, message, debug_id."""
        return {
            'http_status': self.status,
            'name': self.body.get('name', self.body.get('error')),
            'message': self.body.get('message', self.body.get('error_description')),
            'debug_id': self.body.get('debug_id'),
        }


def load_env(path: Path) -> dict[str, str]:
    """Parse a dotenv file into a dict, skipping blanks and comments; never prints values."""
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding='utf-8').splitlines():
        line = raw_line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, _, value = line.partition('=')
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _send(request: urllib.request.Request) -> JsonDict:
    """Send a request and return the JSON body, raising PayPalError on HTTP errors."""
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read()
    except urllib.error.HTTPError as error:
        raw_error = error.read()
        try:
            error_body: JsonDict = json.loads(raw_error) if raw_error else {}
        except json.JSONDecodeError:
            error_body = {'message': 'non-JSON error body'}
        raise PayPalError(error.code, error_body) from error
    parsed: JsonDict = json.loads(raw) if raw else {}
    return parsed


def _basic_auth_request(
    client_id: str, client_secret: str, path: str, data: bytes
) -> urllib.request.Request:
    """Build a form-encoded POST authenticated with the app's client credentials."""
    credentials = base64.b64encode(f'{client_id}:{client_secret}'.encode()).decode()
    return urllib.request.Request(
        f'{API_BASE}{path}',
        data=data,
        headers={
            'Authorization': f'Basic {credentials}',
            'Content-Type': 'application/x-www-form-urlencoded',
        },
        method='POST',
    )


def get_access_token(client_id: str, client_secret: str) -> str:
    """Obtain a client-credentials access token from the sandbox."""
    body = _send(
        _basic_auth_request(
            client_id,
            client_secret,
            '/v1/oauth2/token',
            b'grant_type=client_credentials',
        )
    )
    return str(body['access_token'])


def terminate_token(client_id: str, client_secret: str, token: str) -> None:
    """Revoke a cached access token so the next one carries the app's current permissions."""
    data = urllib.parse.urlencode(
        {'token': token, 'token_type_hint': 'ACCESS_TOKEN'}
    ).encode()
    _send(
        _basic_auth_request(
            client_id, client_secret, '/v1/oauth2/token/terminate', data
        )
    )


class Session:
    """Holds the access token and retries a call once after terminate-and-reissue."""

    def __init__(self, client_id: str, client_secret: str) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._token = get_access_token(client_id, client_secret)

    def _once(
        self, method: str, path: str, payload: JsonDict | None, request_id: str | None
    ) -> JsonDict:
        headers = {
            'Authorization': f'Bearer {self._token}',
            'Content-Type': 'application/json',
            'Prefer': 'return=representation',
        }
        if request_id is not None:
            headers['PayPal-Request-Id'] = request_id
        data = json.dumps(payload).encode() if payload is not None else None
        request = urllib.request.Request(
            f'{API_BASE}{path}', data=data, headers=headers, method=method
        )
        return _send(request)

    def call(
        self,
        method: str,
        path: str,
        payload: JsonDict | None = None,
        request_id: str | None = None,
    ) -> JsonDict:
        """Call a PayPal endpoint; on 401 or 403 NOT_AUTHORIZED, renew the token once and retry.

        The retry reuses the same ``request_id`` so it cannot create a second order.
        """
        try:
            return self._once(method, path, payload, request_id)
        except PayPalError as error:
            not_authorized = error.status == 401 or (
                error.status == 403 and error.body.get('name') == 'NOT_AUTHORIZED'
            )
            if not not_authorized:
                raise
            terminate_token(self._client_id, self._client_secret, self._token)
            self._token = get_access_token(self._client_id, self._client_secret)
            return self._once(method, path, payload, request_id)


def find_vault_id(saved: JsonDict) -> str:
    """Find the vault payment token id by key name; never prints any value."""
    for key in VAULT_ID_KEYS:
        value = saved.get(key)
        if isinstance(value, str) and value:
            return value
    raise KeyError(
        f'no payment token id in vault_token.json; keys present: {sorted(saved)}'
    )


def parse_time(value: str) -> datetime:
    """Parse a PayPal ISO-8601 timestamp (trailing Z) into an aware UTC datetime."""
    return datetime.fromisoformat(value.replace('Z', '+00:00')).astimezone(timezone.utc)


def iso_z(moment: datetime) -> str:
    """Format a datetime as an ISO-8601 UTC string with a trailing Z."""
    return moment.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def place_hold(session: Session, vault_id: str, number: int) -> JsonDict:
    """Create one vaulted AUTHORIZE order and return the hold's recorded details.

    Never voids or captures. All derived times come from PayPal's ``create_time``.
    """
    order = session.call(
        'POST',
        '/v2/checkout/orders',
        {
            'intent': 'AUTHORIZE',
            'purchase_units': [
                {
                    'amount': {'currency_code': 'USD', 'value': AMOUNT},
                    'description': f'TripPilot reauth spike hold {number}',
                }
            ],
            'payment_source': {'paypal': {'vault_id': vault_id}},
        },
        request_id=f'trippilot-spike-hold-{number}',
    )
    purchases = order.get('purchase_units') or [{}]
    authorizations = (purchases[0].get('payments') or {}).get('authorizations') or []
    if not authorizations:
        raise RuntimeError(
            f'order {order.get("id")} has no authorization (status {order.get("status")})'
        )
    authorization_id = str(authorizations[0]['id'])
    auth = session.call('GET', f'/v2/payments/authorizations/{authorization_id}')
    create_time = parse_time(str(auth['create_time']))
    honor_ends = create_time + timedelta(hours=HONOR_HOURS)
    reauth_not_before = create_time + timedelta(hours=REAUTH_HOURS[number])
    return {
        'hold': number,
        'id': authorization_id,
        'order_id': str(order.get('id')),
        'status': str(auth.get('status')),
        'create_time': str(auth['create_time']),
        'expiration_time': str(auth.get('expiration_time')),
        'honor_ends': iso_z(honor_ends),
        'reauth_not_before': iso_z(reauth_not_before),
    }


def save_results(holds: list[JsonDict]) -> None:
    """Write the (git-ignored) results file; never staged or committed."""
    RESULTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    RESULTS_FILE.write_text(
        json.dumps({'app': APP_LABEL, 'holds': holds}, indent=2) + '\n',
        encoding='utf-8',
    )


def print_hold(hold: JsonDict) -> None:
    """Print the one-line status for a hold."""
    print(
        f'[works] hold {hold["hold"]}: {hold["id"]} {hold["status"]} expires {hold["expiration_time"]}'
    )


def main() -> int:
    """Place any missing holds (at most two in total) and record them; return an exit code."""
    existing: list[JsonDict] = []
    if RESULTS_FILE.exists():
        existing = list(
            json.loads(RESULTS_FILE.read_text(encoding='utf-8')).get('holds', [])
        )
    done = {int(hold['hold']) for hold in existing}
    if done >= set(HOLD_NUMBERS):
        print('Both holds already recorded; making no PayPal calls.')
        for hold in existing:
            print_hold(hold)
        return 0

    try:
        env = load_env(ENV_FILE)
        client_id = env['PAYPAL_CLIENT_ID']
        client_secret = env['PAYPAL_CLIENT_SECRET']
        if not client_id or not client_secret:
            raise KeyError('empty value')
    except KeyError as error:
        print(
            f'missing PAYPAL_CLIENT_ID / PAYPAL_CLIENT_SECRET in .env ({error})',
            file=sys.stderr,
        )
        return 2
    try:
        vault_id = find_vault_id(json.loads(VAULT_FILE.read_text(encoding='utf-8')))
    except (OSError, json.JSONDecodeError, KeyError) as error:
        print(f'cannot read the vault payment token: {error}', file=sys.stderr)
        return 2

    holds = list(existing)
    for hold in existing:
        print_hold(hold)
    try:
        session = Session(client_id, client_secret)
        for number in HOLD_NUMBERS:
            if number in done:
                continue
            hold = place_hold(session, vault_id, number)
            holds.append(hold)
            save_results(holds)  # persist after each hold so a crash cannot lose an id
            print_hold(hold)
    except PayPalError as error:
        print(
            f'[fails] PayPal call failed: {json.dumps(error.summary())}',
            file=sys.stderr,
        )
        return 1
    except RuntimeError as error:
        print(f'[fails] {error}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())

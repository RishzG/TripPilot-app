"""Log in with PayPal spike (decision D-04, one-day time-box), run through the typed client.

The flow is a two-step human-in-the-loop OIDC authorization-code exchange against the staging
app. The redirect lands on a placeholder HTTPS page, so the human pastes the redirected address
back instead of the app receiving the callback.

Subcommands:
- ``terminate-token``: terminate the cached app client-credentials token once. Run it right
  after changing the app's features in the PayPal dashboard (research Pitfall 2), so every
  later process starts with a token that carries the new permissions.
- ``start``: generate a single-use ``state``, save it with a timestamp, print the consent URL.
- ``finish --redirect-url URL``: check ``state`` (exact match, under ten minutes old), exchange
  the code through ``get_paypal_gateway()``, read userinfo, and record PASS with the schema
  that worked and the claim names that came back.
- ``record-fail --reason TEXT``: record FAIL and the reason (no PayPal call), for a time-box
  that ends without PASS, including when the consent screen never returned a code.

Safety properties:
- Identity calls only (consent URL, token exchange, userinfo). No order, capture, void or
  reauthorization is made, and no hold id is read or touched.
- Sandbox only: refuses to run unless ``PAYPAL_MODE=sandbox`` and the API base is a sandbox host.
- The authorization code, the access token and the client secret are never printed, logged or
  written. The results file holds claim names and the first two characters of each identifier
  value, never a full value. Errors are reported through ``PayPalError.summary()``.
- Results go to ``scripts/spikes/results/login_spike.json`` (git-ignored).

Run: ``PAYPAL_MODE=sandbox uv run python scripts/spikes/login_with_paypal.py start``
"""

from __future__ import annotations

import argparse
import asyncio
import json
import secrets
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, urlsplit

import httpx

from trippilot.contracts.paypal import PayPalError, UserInfo
from trippilot.payments import aclose_paypal_gateway, get_paypal_gateway
from trippilot.payments.token_cache import TokenCache
from trippilot.settings import Settings, get_settings

JsonDict = dict[str, Any]

REPO_ROOT = Path(__file__).resolve().parents[2]
RESULTS_FILE = REPO_ROOT / 'scripts' / 'spikes' / 'results' / 'login_spike.json'
REDIRECT_URI = 'https://example.com/trippilot-login-spike'
SCOPES = (
    'openid',
    'profile',
    'email',
    'https://uri.paypal.com/services/paypalattributes',
)
STATE_MAX_AGE_SECONDS = 600
SCHEMA_PRIMARY = 'paypalv1.1'
SCHEMA_FALLBACK = 'openid'
IDENTIFIER_CLAIMS = ('user_id', 'sub', 'payer_id')
HTTP_TIMEOUT_SECONDS = 30.0


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


def _sandbox_problem(settings: Settings) -> str | None:
    """Return why this script must refuse to run with these settings, or None when it is fine."""
    if settings.paypal_mode != 'sandbox':
        return 'refusing to run: set PAYPAL_MODE=sandbox'
    if 'sandbox' not in settings.paypal_api_base:
        return 'refusing to run: PAYPAL_API_BASE is not a sandbox host'
    if not settings.paypal_client_id or not settings.paypal_client_secret.get_secret_value():
        return 'refusing to run: PAYPAL_CLIENT_ID / PAYPAL_CLIENT_SECRET are not set'
    return None


def _consent_url(settings: Settings, state: str) -> str:
    """Build the Log in with PayPal consent URL; it carries only the client id and the state."""
    scope = quote(' '.join(SCOPES), safe='')
    redirect = quote(REDIRECT_URI, safe='')
    return (
        f'{settings.paypal_web_base.rstrip("/")}/connect?flowEntry=static'
        f'&client_id={quote(settings.paypal_client_id, safe="")}'
        f'&response_type=code&scope={scope}&redirect_uri={redirect}&state={quote(state, safe="")}'
    )


def _prefix(value: object) -> str:
    """Return the first two characters of an identifier value (never the whole value)."""
    return str(value)[:2]


# -- terminate-token -------------------------------------------------------------------------


async def cmd_terminate_token() -> int:
    """Terminate the cached app token once so the next process issues one with fresh scopes."""
    settings = get_settings()
    problem = _sandbox_problem(settings)
    if problem is not None:
        print(problem, file=sys.stderr)
        return 2
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as http:
        cache = TokenCache(
            http,
            settings.paypal_api_base,
            settings.paypal_client_id,
            settings.paypal_client_secret,
        )
        try:
            await cache.get()
            terminated = await cache.terminate()
        except PayPalError as error:
            print(f'[fails] terminate-token: {error.summary()}', file=sys.stderr)
            return 1
    if terminated:
        print('[works] terminate-token: PayPal accepted the termination; next token is fresh')
        return 0
    print('[fails] terminate-token: PayPal did not accept the termination', file=sys.stderr)
    return 1


# -- start -----------------------------------------------------------------------------------


def cmd_start() -> int:
    """Save a fresh single-use state and print the consent URL (client id and state only)."""
    settings = get_settings()
    problem = _sandbox_problem(settings)
    if problem is not None:
        print(problem, file=sys.stderr)
        return 2
    previous = _read_results()
    state = secrets.token_urlsafe(24)
    started = _now_iso()
    results: JsonDict = {
        'state': state,
        'state_created_at_epoch': time.time(),
        'state_created_at': started,
        'time_box_started_at': previous.get('time_box_started_at', started),
        'attempts': int(previous.get('attempts', 0)) + 1,
        'redirect_uri': REDIRECT_URI,
    }
    _write_results(results)
    print(_consent_url(settings, state))
    print(f'[works] start: state saved to {RESULTS_FILE.relative_to(REPO_ROOT).as_posix()}')
    return 0


# -- finish ----------------------------------------------------------------------------------


def _claim_summary(info: UserInfo) -> JsonDict:
    """Summarise a userinfo response as claim names, presence flags and two-char prefixes."""
    claims = info.claims
    return {
        'claim_names': sorted(str(name) for name in claims),
        'identifier_claims': {
            name: _prefix(claims[name])
            for name in IDENTIFIER_CLAIMS
            if isinstance(claims.get(name), str) and claims[name]
        },
        'has_user_id': bool(claims.get('user_id')),
        'has_sub': bool(claims.get('sub')),
        'has_payer_id': info.payer_id is not None,
        'has_given_name': info.given_name is not None,
        'has_name': info.name is not None,
        'has_email': info.email is not None,
    }


def _parse_redirect(redirect_url: str) -> tuple[str | None, str | None, str | None]:
    """Return (code, state, error text) from the pasted redirected address."""
    query = parse_qs(urlsplit(redirect_url.strip()).query)

    def first(name: str) -> str | None:
        values = query.get(name)
        return values[0] if values else None

    code = first('code')
    state = first('state')
    error = first('error')
    description = first('error_description')
    error_text = None if error is None else f'{error}: {description or "(no description)"}'
    return code, state, error_text


async def cmd_finish(redirect_url: str) -> int:
    """Validate state, exchange the code, read userinfo and record PASS with the claim names."""
    settings = get_settings()
    problem = _sandbox_problem(settings)
    if problem is not None:
        print(problem, file=sys.stderr)
        return 2
    results = _read_results()
    saved_state = results.get('state')
    created = results.get('state_created_at_epoch')
    if not isinstance(saved_state, str) or not isinstance(created, (int, float)):
        print('[fails] finish: no saved state; run `start` first', file=sys.stderr)
        return 1

    code, state, error_text = _parse_redirect(redirect_url)
    if error_text is not None:
        results['last_error'] = f'consent screen returned {error_text}'
        _write_results(results)
        print(f'[fails] finish: PayPal returned an error instead of a code: {error_text}')
        return 1
    if code is None or state is None:
        print('[fails] finish: the redirected URL has no code and state', file=sys.stderr)
        return 1
    if not secrets.compare_digest(state.encode(), saved_state.encode()):
        print('[fails] finish: state does not match the one `start` saved', file=sys.stderr)
        return 1
    age = time.time() - float(created)
    if age > STATE_MAX_AGE_SECONDS:
        print(f'[fails] finish: state is {age:.0f}s old (limit {STATE_MAX_AGE_SECONDS}s)')
        return 1

    gateway = get_paypal_gateway()
    try:
        try:
            tokens = await gateway.exchange_login_code(code=code, redirect_uri=REDIRECT_URI)
        except PayPalError as error:
            results['last_error'] = f'code exchange failed: {error.summary()}'
            results['redirect_uri_sent_with_exchange'] = True
            results['redirect_uri_accepted'] = False
            _write_results(results)
            print(f'[fails] exchange_login_code: {error.summary()}')
            return 1
        print('[works] exchange_login_code (redirect_uri sent with grant_type and code)')

        schema_used = SCHEMA_PRIMARY
        try:
            info = await gateway.get_userinfo(access_token=tokens.access_token, schema=schema_used)
        except PayPalError as first_error:
            print(f'[fails] get_userinfo schema={SCHEMA_PRIMARY}: {first_error.summary()}')
            schema_used = SCHEMA_FALLBACK
            try:
                info = await gateway.get_userinfo(
                    access_token=tokens.access_token, schema=schema_used
                )
            except PayPalError as second_error:
                results['last_error'] = (
                    f'userinfo failed for {SCHEMA_PRIMARY} ({first_error.summary()}) '
                    f'and {SCHEMA_FALLBACK} ({second_error.summary()})'
                )
                results['redirect_uri_sent_with_exchange'] = True
                results['redirect_uri_accepted'] = True
                _write_results(results)
                print(f'[fails] get_userinfo schema={SCHEMA_FALLBACK}: {second_error.summary()}')
                return 1
        print(f'[works] get_userinfo schema={schema_used}')
    finally:
        await aclose_paypal_gateway()

    summary = _claim_summary(info)
    results.update(summary)
    results['verdict'] = 'PASS'
    results['schema'] = schema_used
    results['redirect_uri_sent_with_exchange'] = True
    results['redirect_uri_accepted'] = True
    results['finished_at'] = _now_iso()
    results.pop('last_error', None)
    results.pop('state', None)  # the state is single use and is spent
    _write_results(results)

    print(f'[works] claim_names: {", ".join(summary["claim_names"])}')
    print(f'[works] identifiers (first two chars): {summary["identifier_claims"]}')
    for flag in (
        'has_user_id',
        'has_sub',
        'has_payer_id',
        'has_given_name',
        'has_name',
        'has_email',
    ):
        print(f'[{"works" if summary[flag] else "fails"}] {flag}={summary[flag]}')
    print('verdict: PASS')
    return 0


# -- record-fail -----------------------------------------------------------------------------


def cmd_record_fail(reason: str) -> int:
    """Record FAIL and the reason without calling PayPal (the time-box ended without PASS)."""
    results = _read_results()
    results.pop('state', None)
    results['verdict'] = 'FAIL'
    results['reason'] = reason
    results['finished_at'] = _now_iso()
    _write_results(results)
    print(f'[fails] recorded FAIL: {reason}')
    return 0


# -- entry point -----------------------------------------------------------------------------


def _parser() -> argparse.ArgumentParser:
    """Build the subcommand parser."""
    parser = argparse.ArgumentParser(description='Log in with PayPal spike (D-04).')
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('terminate-token', help='terminate the cached app token once (Pitfall 2)')
    sub.add_parser('start', help='save a state and print the consent URL')
    finish = sub.add_parser('finish', help='exchange the pasted redirected URL and record PASS')
    finish.add_argument('--redirect-url', required=True, help='full redirected address')
    fail = sub.add_parser('record-fail', help='record FAIL at the end of the time-box')
    fail.add_argument('--reason', required=True, help='one-line reason')
    return parser


def main(argv: list[str] | None = None) -> int:
    """Dispatch the chosen subcommand and return the process exit code."""
    args = _parser().parse_args(argv)
    if args.command == 'terminate-token':
        return asyncio.run(cmd_terminate_token())
    if args.command == 'start':
        return cmd_start()
    if args.command == 'finish':
        return asyncio.run(cmd_finish(args.redirect_url))
    return cmd_record_fail(args.reason)


if __name__ == '__main__':
    sys.exit(main())

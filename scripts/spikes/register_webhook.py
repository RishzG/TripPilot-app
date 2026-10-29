"""Register (or reuse) this environment's PayPal webhook for the TripPilot endpoint (plan 01-13).

D-32, UD-1: the staging webhook is registered on the staging PayPal app; production registers its
own in 01-17. The script asks PayPal which webhook event names exist, prints which of the
research subscription names are confirmed, then either reuses the webhook already registered for
exactly this URL or creates one subscribed to the confirmed names. It prints the webhook id (an id
is not a secret) and records the outcome in scripts/spikes/results/webhook_registration.json
(gitignored). It never prints or writes a credential.

Safe to re-run: a second run finds the webhook for the same URL and creates nothing. A webhook
that PayPal reports as already existing for the URL (a race, or one created by hand) is reused too.
Subscription changes to an existing webhook are reported, not made.

Calls (sandbox only; the script refuses any other host):
- ``POST /v1/oauth2/token`` (client credentials)
- ``GET  /v1/notifications/webhooks-event-types``
- ``GET  /v1/notifications/webhooks``
- ``POST /v1/notifications/webhooks`` only when no webhook exists for the URL

Run: ``PAYPAL_MODE=sandbox uv run python scripts/spikes/register_webhook.py --url
https://<host>/api/paypal/webhooks``. Credentials come from Settings (the environment and ``.env``).
Afterwards set the printed id as PAYPAL_WEBHOOK_ID on that environment's web AND worker services.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from trippilot.contracts.paypal import PayPalError, Webhook
from trippilot.payments.client import PayPalClient
from trippilot.settings import get_settings

WEBHOOK_PATH = '/api/paypal/webhooks'
RESULTS_FILE = Path(__file__).resolve().parent / 'results' / 'webhook_registration.json'
DUPLICATE_URL_ERROR = 'WEBHOOK_URL_ALREADY_EXISTS'

RESEARCH_EVENT_NAMES = (
    'PAYMENT.AUTHORIZATION.CREATED',
    'PAYMENT.AUTHORIZATION.VOIDED',
    'PAYMENT.CAPTURE.COMPLETED',
    'PAYMENT.CAPTURE.DECLINED',
    'PAYMENT.CAPTURE.PENDING',
    'PAYMENT.CAPTURE.REFUNDED',
    'CHECKOUT.ORDER.APPROVED',
    'CHECKOUT.ORDER.COMPLETED',
    'PAYMENT.PAYOUTS-ITEM.SUCCEEDED',
    'PAYMENT.PAYOUTS-ITEM.FAILED',
    'PAYMENT.PAYOUTSBATCH.SUCCESS',
    'VAULT.PAYMENT-TOKEN.CREATED',
    'VAULT.PAYMENT-TOKEN.DELETED',
    'IDENTITY.AUTHORIZATION-CONSENT.REVOKED',
)
"""The subscription list from 01-RESEARCH.md (PayPal's event-names page)."""


def _url_problem(url: str) -> str | None:
    """Return why the URL cannot be a PayPal webhook for TripPilot, or None when it can."""
    parts = urlsplit(url)
    if parts.scheme != 'https' or not parts.netloc:
        return 'the URL must be https (PayPal only delivers to public HTTPS hosts)'
    if parts.hostname in ('localhost', '127.0.0.1', '::1'):
        return 'the URL must be a public host, not localhost'
    if parts.path != WEBHOOK_PATH or parts.query or parts.fragment:
        return f'the URL path must be exactly {WEBHOOK_PATH}'
    return None


def _record(
    *,
    url: str,
    webhook: Webhook,
    reused: bool,
    available: tuple[str, ...],
    confirmed: list[str],
    missing: list[str],
    other_webhooks: int,
) -> None:
    """Write the outcome (names and ids only) to the gitignored results file."""
    RESULTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    result = {
        'recorded_at': datetime.now(UTC).isoformat(timespec='seconds'),
        'mode': 'sandbox',
        'url': url,
        'webhook_id': webhook.id,
        'reused_existing_webhook': reused,
        'research_event_names': list(RESEARCH_EVENT_NAMES),
        'confirmed_event_names': confirmed,
        'missing_event_names': missing,
        'subscribed_event_names': list(webhook.event_types),
        'subscribed_but_not_confirmed': sorted(set(webhook.event_types) - set(available)),
        'confirmed_but_not_subscribed': sorted(set(confirmed) - set(webhook.event_types)),
        'available_event_type_count': len(available),
        'other_webhooks_on_this_app': other_webhooks,
    }
    RESULTS_FILE.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')


async def _register(client: PayPalClient, url: str) -> int:
    """Confirm the event names, then reuse or create the webhook for the URL."""
    available = await client.list_webhook_event_types()
    known = set(available)
    confirmed = [name for name in RESEARCH_EVENT_NAMES if name in known]
    missing = [name for name in RESEARCH_EVENT_NAMES if name not in known]
    print(f'event types offered by PayPal: {len(available)}')
    for name in confirmed:
        print(f'  confirmed: {name}')
    for name in missing:
        print(f'  NOT offered: {name}')
    if not confirmed:
        print('none of the research event names exist; refusing to register', file=sys.stderr)
        return 1

    existing = await client.list_webhooks()
    match = next((hook for hook in existing if hook.url == url), None)
    reused = match is not None
    if match is None:
        try:
            match = await client.create_webhook(url=url, event_types=confirmed)
        except PayPalError as error:
            if error.name != DUPLICATE_URL_ERROR:
                raise
            # PayPal says the URL is already registered: pick it up from a fresh list.
            existing = await client.list_webhooks()
            match = next((hook for hook in existing if hook.url == url), None)
            if match is None:
                raise
            reused = True
    webhook = match

    print(f'{"reused" if reused else "created"} webhook for {url}')
    print(f'webhook_id: {webhook.id}')
    unsubscribed = sorted(set(confirmed) - set(webhook.event_types))
    if reused and unsubscribed:
        print('this existing webhook is not subscribed to (not changed by this script):')
        for name in unsubscribed:
            print(f'  {name}')
    others = len([hook for hook in existing if hook.id != webhook.id])
    _record(
        url=url,
        webhook=webhook,
        reused=reused,
        available=available,
        confirmed=confirmed,
        missing=missing,
        other_webhooks=others,
    )
    print(f'recorded in {RESULTS_FILE}')
    return 0


async def run(url: str) -> int:
    """Validate the inputs, register or reuse the webhook and return the exit code."""
    problem = _url_problem(url)
    if problem is not None:
        print(f'refusing to run: {problem}', file=sys.stderr)
        return 2
    settings = get_settings()
    if settings.paypal_mode != 'sandbox':
        print('refusing to run: set PAYPAL_MODE=sandbox', file=sys.stderr)
        return 2
    if 'sandbox' not in settings.paypal_api_base:
        print('refusing to run: PAYPAL_API_BASE is not a sandbox host', file=sys.stderr)
        return 2
    if not settings.paypal_client_id or not settings.paypal_client_secret.get_secret_value():
        print(
            'refusing to run: PAYPAL_CLIENT_ID / PAYPAL_CLIENT_SECRET are not set', file=sys.stderr
        )
        return 2

    async with httpx.AsyncClient(timeout=30.0) as http:
        client = PayPalClient(
            http,
            settings.paypal_api_base,
            settings.paypal_web_base,
            settings.paypal_client_id,
            settings.paypal_client_secret,
        )
        try:
            return await _register(client, url)
        except PayPalError as error:
            print(f'paypal_error: {error.summary()}', file=sys.stderr)
            return 1


def main() -> int:
    """Parse the command line and run."""
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0] if __doc__ else None)
    parser.add_argument(
        '--url',
        required=True,
        help=f'public HTTPS webhook URL, ending in {WEBHOOK_PATH}',
    )
    args = parser.parse_args()
    return asyncio.run(run(str(args.url)))


if __name__ == '__main__':
    sys.exit(main())

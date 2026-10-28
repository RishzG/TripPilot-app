"""Read-only live check of the typed PayPal client against the real sandbox (plan 01-03).

It fetches a client-credentials token, reports whether the vault scope is present, and lists the
webhook event types. The only POST is the OAuth token request; nothing is created, captured,
voided or reauthorized, and no hold id is read or touched (01-18 reads the holds).

Safety properties:
- Sandbox only: refuses to run unless the configured API base is a sandbox host.
- Secrets are never printed. Errors are reported through `PayPalError.summary()`.

Run: ``PAYPAL_MODE=sandbox uv run python scripts/spikes/check_paypal_client.py``
"""

from __future__ import annotations

import asyncio
import sys

import httpx

from trippilot.contracts.paypal import PayPalError
from trippilot.payments.client import PayPalClient
from trippilot.settings import get_settings

VAULT_SCOPE = 'https://uri.paypal.com/services/vault/payment-tokens/readwrite'


async def run() -> int:
    """Run the read-only checks and return the process exit code."""
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
            scopes = await client.access_token_scopes()
            event_types = await client.list_webhook_event_types()
        except PayPalError as error:
            print(f'paypal_error: {error.summary()}', file=sys.stderr)
            return 1

    print(f'vault_scope: {"present" if VAULT_SCOPE in scopes else "absent"}')
    print(f'scope_count: {len(scopes)}')
    print(f'event_types: {len(event_types)}')
    return 0 if event_types else 1


if __name__ == '__main__':
    sys.exit(asyncio.run(run()))

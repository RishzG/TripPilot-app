"""The `trippilot.payments` package: the only place PayPal I/O may live (D-53, D-54).

Single writer of this `__init__.py`: plan 01-03. Later plans add modules inside the package
without editing it: 01-08 `models`, `vault_store`, `ledger` and `vault_flow`; 01-13 `webhooks`;
01-14 `pool`; 01-21 `router` and `tasks`.

Other packages obtain PayPal through `get_paypal_gateway()` (a FastAPI dependency returning the
`PayPalGateway` Protocol from `trippilot.contracts.paypal`). They must never import
`payments.client`, `payments.token_cache` or `payments.vault_store`; `importlinter.ini` and
`tests/unit/test_import_boundaries.py` enforce that.
"""

from __future__ import annotations

import httpx

from trippilot.contracts.paypal import PayPalGateway
from trippilot.payments.client import PayPalClient
from trippilot.payments.fake import FakePayPal
from trippilot.settings import get_settings

HTTP_TIMEOUT_SECONDS = 30.0


class _Holder:
    """Process-wide gateway state (a class attribute holder, so no `global` statements)."""

    gateway: PayPalGateway | None = None
    http: httpx.AsyncClient | None = None


def get_paypal_gateway() -> PayPalGateway:
    """Return the process-wide gateway: `FakePayPal` for `PAYPAL_MODE=fake`, else `PayPalClient`.

    The sandbox client shares one `httpx.AsyncClient`, so its token cache is shared too. Usable
    directly as a FastAPI dependency.
    """
    if _Holder.gateway is not None:
        return _Holder.gateway
    settings = get_settings()
    gateway: PayPalGateway
    if settings.paypal_mode == 'fake':
        gateway = FakePayPal()
    else:
        _Holder.http = httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS)
        gateway = PayPalClient(
            _Holder.http,
            settings.paypal_api_base,
            settings.paypal_web_base,
            settings.paypal_client_id,
            settings.paypal_client_secret,
        )
    _Holder.gateway = gateway
    return gateway


def reset_paypal_gateway() -> None:
    """Forget the process-wide gateway so the next `get_paypal_gateway()` rebuilds it (tests)."""
    _Holder.gateway = None
    _Holder.http = None


async def aclose_paypal_gateway() -> None:
    """Close the shared HTTP client, if one was created. Call at application shutdown."""
    if _Holder.http is not None:
        await _Holder.http.aclose()

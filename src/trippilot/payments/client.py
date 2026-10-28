"""Typed httpx PayPal client (RED stub)."""

from __future__ import annotations

import httpx
from pydantic import SecretStr

from trippilot.contracts.money import Cents
from trippilot.contracts.paypal import (
    Authorization,
    Capture,
    PaymentToken,
    VaultedAuthorization,
)


class PayPalClient:
    """Stub: only the methods the RED tests call, all unimplemented."""

    def __init__(
        self,
        http: httpx.AsyncClient,
        base_url: str,
        web_base: str,
        client_id: str,
        client_secret: SecretStr,
    ) -> None:
        """Stub constructor."""
        self.http = http

    async def create_payment_token(self, *, request_id: str, setup_token_id: str) -> PaymentToken:
        """Stub: not implemented yet."""
        raise NotImplementedError

    async def capture_authorization(
        self, *, request_id: str, authorization_id: str, amount: Cents, final_capture: bool
    ) -> Capture:
        """Stub: not implemented yet."""
        raise NotImplementedError

    async def create_order_authorize_vaulted(
        self, *, request_id: str, payment_token_id: str, amount: Cents, description: str
    ) -> VaultedAuthorization:
        """Stub: not implemented yet."""
        raise NotImplementedError

    async def void_authorization(self, *, request_id: str, authorization_id: str) -> Authorization:
        """Stub: not implemented yet."""
        raise NotImplementedError

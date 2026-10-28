"""The PayPal gateway contract: Protocol, frozen DTOs and the typed error.

Both build tracks depend on this module (D-53, D-54). `trippilot.payments.client.PayPalClient`
talks to the real sandbox and `trippilot.payments.fake.FakePayPal` is the in-memory double.
Every mutating method takes a caller-supplied, keyword-only `request_id` that is sent as the
`PayPal-Request-Id` header and reused on retries; implementations never mint ids themselves.
Money crosses this boundary as integer `Cents`.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Protocol

from pydantic import SecretStr

from trippilot.contracts.money import Cents


class PayPalError(Exception):
    """A non-success PayPal response carrying only fields that are safe to log.

    The raw response body is deliberately not stored: it can echo tokens or personal data.
    """

    def __init__(
        self,
        status: int,
        name: str | None = None,
        message: str | None = None,
        debug_id: str | None = None,
        details: Sequence[Mapping[str, object]] = (),
    ) -> None:
        """Record the HTTP status and the safe error fields."""
        self.status = status
        self.name = name
        self.message = message
        self.debug_id = debug_id
        self.details: tuple[Mapping[str, object], ...] = tuple(details)
        text = f'PayPal returned HTTP {status}: {name or ""} {message or ""}'.strip()
        super().__init__(text)

    def summary(self) -> dict[str, object]:
        """Return the loggable fields: status, name, message, debug id and issue codes."""
        issues = [str(item['issue']) for item in self.details if 'issue' in item]
        return {
            'http_status': self.status,
            'name': self.name,
            'message': self.message,
            'debug_id': self.debug_id,
            'issues': issues,
        }


@dataclass(frozen=True)
class SetupToken:
    """A vault setup token handed to the browser so the buyer can approve saving PayPal."""

    id: str


@dataclass(frozen=True)
class PaymentToken:
    """A vaulted payment method for a buyer."""

    id: str
    customer_id: str | None
    payer_id: str | None
    email: str | None


@dataclass(frozen=True)
class VaultedAuthorization:
    """The authorization created inside a vaulted create-order call (no separate authorize)."""

    order_id: str
    authorization_id: str
    status: str


@dataclass(frozen=True)
class Order:
    """A created order and the buyer approval link, when PayPal returned one."""

    id: str
    status: str
    approve_url: str | None


@dataclass(frozen=True)
class Authorization:
    """A payment authorization (hold) and its validity timestamps as PayPal reported them."""

    id: str
    status: str
    amount: Cents
    create_time: str | None
    expiration_time: str | None


@dataclass(frozen=True)
class Capture:
    """A capture taken against an authorization."""

    id: str
    status: str
    amount: Cents


@dataclass(frozen=True)
class LoginTokens:
    """Tokens from a Log in with PayPal code exchange; the access token is a secret."""

    access_token: SecretStr


@dataclass(frozen=True)
class UserInfo:
    """Identity claims from the userinfo endpoint, read through tolerant accessors."""

    claims: Mapping[str, object] = field(default_factory=dict)

    def _first(self, *names: str) -> str | None:
        """Return the first present, non-empty string claim among `names`."""
        for name in names:
            value = self.claims.get(name)
            if isinstance(value, str) and value:
                return value
        return None

    @property
    def subject(self) -> str | None:
        """The stable PayPal user identifier (`sub` or `user_id`)."""
        return self._first('sub', 'user_id')

    @property
    def payer_id(self) -> str | None:
        """The PayPal payer id, when the requested schema returns one."""
        return self._first('payer_id')

    @property
    def email(self) -> str | None:
        """The account email: the `email` claim, else the primary entry of `emails`."""
        direct = self._first('email')
        if direct is not None:
            return direct
        emails = self.claims.get('emails')
        if isinstance(emails, list):
            entries = [item for item in emails if isinstance(item, Mapping)]
            primary = [item for item in entries if item.get('primary')]
            for item in primary + entries:
                value = item.get('value')
                if isinstance(value, str) and value:
                    return value
        return None

    @property
    def name(self) -> str | None:
        """The display name."""
        return self._first('name')

    @property
    def given_name(self) -> str | None:
        """The given (first) name."""
        return self._first('given_name')


@dataclass(frozen=True)
class Webhook:
    """A registered webhook endpoint and the event types it receives."""

    id: str
    url: str
    event_types: tuple[str, ...]


class PayPalGateway(Protocol):
    """Every PayPal operation the app needs; mutating methods require a `request_id`."""

    async def access_token_scopes(self) -> tuple[str, ...]:
        """Return the scopes of the cached client-credentials token (fetching one if needed)."""
        ...

    async def create_setup_token(
        self, *, request_id: str, return_url: str, cancel_url: str
    ) -> SetupToken:
        """Create a vault setup token for a buyer to approve."""
        ...

    async def create_payment_token(self, *, request_id: str, setup_token_id: str) -> PaymentToken:
        """Turn an approved setup token into a vaulted payment token."""
        ...

    async def delete_payment_token(self, *, payment_token_id: str) -> None:
        """Delete a vaulted payment token."""
        ...

    async def create_order_authorize_vaulted(
        self, *, request_id: str, payment_token_id: str, amount: Cents, description: str
    ) -> VaultedAuthorization:
        """Create an AUTHORIZE order from a vaulted token; the hold exists on return."""
        ...

    async def create_order_authorize(
        self,
        *,
        request_id: str,
        amount: Cents,
        description: str,
        return_url: str,
        cancel_url: str,
    ) -> Order:
        """Create an AUTHORIZE order that the buyer approves in the browser."""
        ...

    async def authorize_order(self, *, request_id: str, order_id: str) -> Authorization:
        """Authorize an approved order and return the resulting authorization."""
        ...

    async def get_authorization(self, authorization_id: str) -> Authorization:
        """Read an authorization (read-only)."""
        ...

    async def reauthorize(
        self, *, request_id: str, authorization_id: str, amount: Cents | None
    ) -> Authorization:
        """Reauthorize a hold, optionally for a different amount."""
        ...

    async def capture_authorization(
        self, *, request_id: str, authorization_id: str, amount: Cents, final_capture: bool
    ) -> Capture:
        """Capture `amount` against an authorization; `final_capture` releases the remainder."""
        ...

    async def void_authorization(self, *, request_id: str, authorization_id: str) -> Authorization:
        """Void an authorization and return its state afterwards."""
        ...

    async def verify_webhook_signature(
        self, *, headers: Mapping[str, str], raw_body: bytes, webhook_id: str
    ) -> bool:
        """Ask PayPal whether a webhook delivery is genuine, using the unmodified raw body."""
        ...

    async def create_webhook(self, *, url: str, event_types: Sequence[str]) -> Webhook:
        """Register a webhook endpoint for the given event types."""
        ...

    async def list_webhooks(self) -> tuple[Webhook, ...]:
        """List the webhooks registered for the app."""
        ...

    async def list_webhook_event_types(self) -> tuple[str, ...]:
        """List the names of every webhook event type PayPal offers."""
        ...

    async def exchange_login_code(self, *, code: str, redirect_uri: str) -> LoginTokens:
        """Exchange a Log in with PayPal authorization code for tokens."""
        ...

    async def get_userinfo(self, *, access_token: SecretStr, schema: str) -> UserInfo:
        """Fetch identity claims with the user's own access token."""
        ...

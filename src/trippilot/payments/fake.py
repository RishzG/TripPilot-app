"""In-memory PayPal gateway double for Track B tests (D-53).

`FakePayPal` implements `PayPalGateway` with no network. It behaves like PayPal where the
app depends on it:

- Results are memoised per `(method, request_id)`: repeating a request id returns the stored
  result, runs nothing again and records no new call. A call that failed stores nothing, so the
  same request id runs for real on the next attempt.
- Authorizations follow `CREATED -> PARTIALLY_CAPTURED -> CAPTURED`, or `-> VOIDED`; illegal
  moves and over-captures raise `PayPalError`.
- `fail_next(method, error)` makes only the next executed call of that method raise.
- A vaulted hold needs a payment token the fake issued and has not deleted.
- Login codes are single use, like PayPal's.

Ids are deterministic (`FAKE-ORDER-0001`, `FAKE-AUTH-0001`, ...) and every executed call is
appended to `calls` as `(method, arguments)`.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import TypeVar, cast

from pydantic import SecretStr

from trippilot.contracts.money import Cents
from trippilot.contracts.paypal import (
    Authorization,
    Capture,
    LoginTokens,
    Order,
    PaymentToken,
    PayPalError,
    SetupToken,
    UserInfo,
    VaultedAuthorization,
    Webhook,
)

T = TypeVar('T')

VAULT_SCOPE = 'https://uri.paypal.com/services/vault/payment-tokens/readwrite'
CREATE_TIME = '2026-01-01T00:00:00Z'
EXPIRATION_TIME = '2026-01-30T00:00:00Z'
DEFAULT_EVENT_TYPES = (
    'PAYMENT.AUTHORIZATION.CREATED',
    'PAYMENT.AUTHORIZATION.VOIDED',
    'PAYMENT.CAPTURE.COMPLETED',
    'PAYMENT.CAPTURE.DENIED',
    'PAYMENT.CAPTURE.REFUNDED',
    'CHECKOUT.ORDER.APPROVED',
    'VAULT.PAYMENT-TOKEN.CREATED',
    'VAULT.PAYMENT-TOKEN.DELETED',
)


@dataclass
class _AuthState:
    """Mutable server-side state of one fake authorization."""

    id: str
    amount: Cents
    status: str = 'CREATED'
    captured: int = 0
    expiration_time: str = EXPIRATION_TIME

    def dto(self) -> Authorization:
        """Snapshot the state as the public DTO."""
        return Authorization(
            id=self.id,
            status=self.status,
            amount=self.amount,
            create_time=CREATE_TIME,
            expiration_time=self.expiration_time,
        )


class FakePayPal:
    """An in-memory `PayPalGateway` with idempotency, failure injection and login support."""

    def __init__(self) -> None:
        """Create an empty fake with the default vault scope and a passing webhook verdict."""
        self.calls: list[tuple[str, dict[str, object]]] = []
        self.webhook_verdict: bool = True
        self.scopes: tuple[str, ...] = ('openid', VAULT_SCOPE)
        self.event_types: tuple[str, ...] = DEFAULT_EVENT_TYPES
        self.payment_tokens: dict[str, PaymentToken] = {}
        self.authorizations: dict[str, _AuthState] = {}
        self._setup_tokens: set[str] = set()
        self._orders: dict[str, Cents] = {}
        self._webhooks: dict[str, Webhook] = {}
        self._logins: dict[str, Mapping[str, object]] = {}
        self._login_tokens: dict[str, Mapping[str, object]] = {}
        self._memo: dict[tuple[str, str], object] = {}
        self._failures: dict[str, list[PayPalError]] = {}
        self._counters: dict[str, int] = {}

    # -- test controls -----------------------------------------------------------------------

    def fail_next(self, method: str, error: PayPalError) -> None:
        """Make the next executed call of `method` raise `error` (one-shot, queued in order)."""
        if method.startswith('_') or not callable(getattr(type(self), method, None)):
            raise ValueError(f'FakePayPal has no gateway method {method!r}')
        self._failures.setdefault(method, []).append(error)

    def register_login(self, code: str, claims: Mapping[str, object]) -> None:
        """Make `exchange_login_code(code=code)` succeed once and yield `claims` from userinfo."""
        self._logins[code] = claims

    # -- internals ---------------------------------------------------------------------------

    def _next_id(self, kind: str) -> str:
        """Return the next deterministic id such as `FAKE-AUTH-0001`."""
        count = self._counters.get(kind, 0) + 1
        self._counters[kind] = count
        return f'FAKE-{kind}-{count:04d}'

    def _run(
        self,
        method: str,
        args: dict[str, object],
        produce: Callable[[], T],
        request_id: str | None = None,
    ) -> T:
        """Replay a memoised result, else record the call, apply injected failures and run."""
        key = (method, request_id) if request_id is not None else None
        if key is not None and key in self._memo:
            return cast(T, self._memo[key])
        self.calls.append((method, args))
        queue = self._failures.get(method)
        if queue:
            raise queue.pop(0)
        result = produce()
        if key is not None:
            self._memo[key] = result
        return result

    def _auth(self, authorization_id: str) -> _AuthState:
        """Look up an authorization or raise PayPal's 404."""
        state = self.authorizations.get(authorization_id)
        if state is None:
            raise PayPalError(404, 'INVALID_RESOURCE_ID', f'no authorization {authorization_id}')
        return state

    def _new_authorization(self, amount: Cents) -> _AuthState:
        """Create and store a fresh authorization in the CREATED state."""
        state = _AuthState(id=self._next_id('AUTH'), amount=amount)
        self.authorizations[state.id] = state
        return state

    # -- token scopes ------------------------------------------------------------------------

    async def access_token_scopes(self) -> tuple[str, ...]:
        """Return the configured scopes."""
        return self._run('access_token_scopes', {}, lambda: self.scopes)

    # -- vault -------------------------------------------------------------------------------

    async def create_setup_token(
        self, *, request_id: str, return_url: str, cancel_url: str
    ) -> SetupToken:
        """Issue a setup token."""

        def produce() -> SetupToken:
            token = SetupToken(id=self._next_id('SETUP'))
            self._setup_tokens.add(token.id)
            return token

        args: dict[str, object] = {'return_url': return_url, 'cancel_url': cancel_url}
        return self._run('create_setup_token', args, produce, request_id)

    async def create_payment_token(self, *, request_id: str, setup_token_id: str) -> PaymentToken:
        """Turn a known setup token into a payment token."""

        def produce() -> PaymentToken:
            if setup_token_id not in self._setup_tokens:
                raise PayPalError(404, 'INVALID_RESOURCE_ID', f'no setup token {setup_token_id}')
            token_id = self._next_id('PT')
            number = token_id.removeprefix('FAKE-PT-')
            token = PaymentToken(
                id=token_id,
                customer_id=f'FAKE-CUST-{number}',
                payer_id=f'FAKE-PAYER-{number}',
                email=f'buyer{number}@example.test',
            )
            self.payment_tokens[token.id] = token
            return token

        args: dict[str, object] = {'setup_token_id': setup_token_id}
        return self._run('create_payment_token', args, produce, request_id)

    async def delete_payment_token(self, *, payment_token_id: str) -> None:
        """Delete a payment token so it can no longer hold."""

        def produce() -> None:
            if self.payment_tokens.pop(payment_token_id, None) is None:
                raise PayPalError(404, 'INVALID_RESOURCE_ID', f'no token {payment_token_id}')

        self._run('delete_payment_token', {'payment_token_id': payment_token_id}, produce)

    # -- orders ------------------------------------------------------------------------------

    async def create_order_authorize_vaulted(
        self, *, request_id: str, payment_token_id: str, amount: Cents, description: str
    ) -> VaultedAuthorization:
        """Create a hold from a vaulted token the fake issued and has not deleted."""

        def produce() -> VaultedAuthorization:
            if payment_token_id not in self.payment_tokens:
                raise PayPalError(422, 'INVALID_PAYMENT_TOKEN', f'unknown token {payment_token_id}')
            order_id = self._next_id('ORDER')
            self._orders[order_id] = amount
            state = self._new_authorization(amount)
            return VaultedAuthorization(order_id, state.id, state.status)

        args: dict[str, object] = {
            'payment_token_id': payment_token_id,
            'amount': amount,
            'description': description,
        }
        return self._run('create_order_authorize_vaulted', args, produce, request_id)

    async def create_order_authorize(
        self,
        *,
        request_id: str,
        amount: Cents,
        description: str,
        return_url: str,
        cancel_url: str,
    ) -> Order:
        """Create a browser-approval order."""

        def produce() -> Order:
            order_id = self._next_id('ORDER')
            self._orders[order_id] = amount
            return Order(
                order_id, 'CREATED', f'https://fake.paypal.test/checkoutnow?token={order_id}'
            )

        args: dict[str, object] = {
            'amount': amount,
            'description': description,
            'return_url': return_url,
            'cancel_url': cancel_url,
        }
        return self._run('create_order_authorize', args, produce, request_id)

    async def authorize_order(self, *, request_id: str, order_id: str) -> Authorization:
        """Authorize an order, creating its hold."""

        def produce() -> Authorization:
            amount = self._orders.get(order_id)
            if amount is None:
                raise PayPalError(404, 'INVALID_RESOURCE_ID', f'no order {order_id}')
            return self._new_authorization(amount).dto()

        return self._run('authorize_order', {'order_id': order_id}, produce, request_id)

    # -- authorizations ----------------------------------------------------------------------

    async def get_authorization(self, authorization_id: str) -> Authorization:
        """Read an authorization."""
        return self._run(
            'get_authorization',
            {'authorization_id': authorization_id},
            lambda: self._auth(authorization_id).dto(),
        )

    async def reauthorize(
        self, *, request_id: str, authorization_id: str, amount: Cents | None
    ) -> Authorization:
        """Reauthorize a live hold, optionally changing its amount."""

        def produce() -> Authorization:
            state = self._auth(authorization_id)
            if state.status not in ('CREATED', 'PARTIALLY_CAPTURED'):
                raise PayPalError(422, 'AUTHORIZATION_NOT_ACTIVE', f'status is {state.status}')
            if amount is not None:
                state.amount = amount
            return state.dto()

        args: dict[str, object] = {'authorization_id': authorization_id, 'amount': amount}
        return self._run('reauthorize', args, produce, request_id)

    async def capture_authorization(
        self, *, request_id: str, authorization_id: str, amount: Cents, final_capture: bool
    ) -> Capture:
        """Capture part of a live hold; a final capture releases the remainder."""

        def produce() -> Capture:
            state = self._auth(authorization_id)
            if state.status == 'VOIDED':
                raise PayPalError(422, 'AUTHORIZATION_VOIDED', 'the authorization was voided')
            if state.status == 'CAPTURED':
                raise PayPalError(422, 'AUTHORIZATION_ALREADY_CAPTURED', 'final capture was taken')
            if state.captured + amount > state.amount:
                raise PayPalError(
                    422, 'AMOUNT_EXCEEDS_AUTHORIZATION', 'capture exceeds the authorized amount'
                )
            state.captured += amount
            state.status = 'CAPTURED' if final_capture else 'PARTIALLY_CAPTURED'
            return Capture(self._next_id('CAPTURE'), 'COMPLETED', amount)

        args: dict[str, object] = {
            'authorization_id': authorization_id,
            'amount': amount,
            'final_capture': final_capture,
        }
        return self._run('capture_authorization', args, produce, request_id)

    async def void_authorization(self, *, request_id: str, authorization_id: str) -> Authorization:
        """Void a hold that has not been finally captured."""

        def produce() -> Authorization:
            state = self._auth(authorization_id)
            if state.status == 'CAPTURED':
                raise PayPalError(422, 'AUTHORIZATION_ALREADY_CAPTURED', 'already captured')
            if state.status == 'VOIDED':
                raise PayPalError(422, 'AUTHORIZATION_ALREADY_VOIDED', 'already voided')
            state.status = 'VOIDED'
            return state.dto()

        return self._run(
            'void_authorization', {'authorization_id': authorization_id}, produce, request_id
        )

    # -- webhooks ----------------------------------------------------------------------------

    async def verify_webhook_signature(
        self, *, headers: Mapping[str, str], raw_body: bytes, webhook_id: str
    ) -> bool:
        """Return the configured `webhook_verdict`."""
        args: dict[str, object] = {'webhook_id': webhook_id, 'raw_body': raw_body}
        return self._run('verify_webhook_signature', args, lambda: self.webhook_verdict)

    async def create_webhook(self, *, url: str, event_types: Sequence[str]) -> Webhook:
        """Register a webhook."""

        def produce() -> Webhook:
            hook = Webhook(self._next_id('WH'), url, tuple(event_types))
            self._webhooks[hook.id] = hook
            return hook

        return self._run('create_webhook', {'url': url, 'event_types': tuple(event_types)}, produce)

    async def list_webhooks(self) -> tuple[Webhook, ...]:
        """List registered webhooks."""
        return self._run('list_webhooks', {}, lambda: tuple(self._webhooks.values()))

    async def list_webhook_event_types(self) -> tuple[str, ...]:
        """List the configured event type names."""
        return self._run('list_webhook_event_types', {}, lambda: self.event_types)

    # -- Log in with PayPal ------------------------------------------------------------------

    async def exchange_login_code(self, *, code: str, redirect_uri: str) -> LoginTokens:
        """Exchange a registered code once; unknown or used codes raise `invalid_grant`."""

        def produce() -> LoginTokens:
            claims = self._logins.pop(code, None)
            if claims is None:
                raise PayPalError(400, 'invalid_grant', 'unknown or already used code')
            token = f'fake-login-token-{code}'
            self._login_tokens[token] = claims
            return LoginTokens(access_token=SecretStr(token))

        args: dict[str, object] = {'code': code, 'redirect_uri': redirect_uri}
        return self._run('exchange_login_code', args, produce)

    async def get_userinfo(self, *, access_token: SecretStr, schema: str) -> UserInfo:
        """Return the claims registered for the code that produced `access_token`."""

        def produce() -> UserInfo:
            claims = self._login_tokens.get(access_token.get_secret_value())
            if claims is None:
                raise PayPalError(401, 'invalid_token', 'unknown access token')
            return UserInfo(claims=claims)

        return self._run('get_userinfo', {'schema': schema}, produce)

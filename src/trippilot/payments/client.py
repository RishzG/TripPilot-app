"""Typed httpx implementation of the PayPal gateway contract.

This module is the single choke point for PayPal I/O. Rules baked in:

- Every mutating method takes a caller-supplied `request_id`, sent as `PayPal-Request-Id` and
  reused on the one retry. The client never mints ids itself (callers own idempotency).
- On a 401, or a 403 named `NOT_AUTHORIZED`, the cached token is terminated and the call is
  retried exactly once (PayPal fixes a token's permissions at issue time). Termination is
  `TokenCache.terminate`, which POSTs `/v1/oauth2/token/terminate`.
- Money enters and leaves as integer `Cents`; the two-decimal string exists only here.
- Non-2xx responses raise `PayPalError`, which carries only loggable fields.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any
from urllib.parse import quote

import httpx
from pydantic import SecretStr

from trippilot.contracts.money import Cents, from_paypal_value, to_paypal_value
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
from trippilot.payments.token_cache import TokenCache

JsonDict = dict[str, Any]

CURRENCY = 'USD'
BRAND_NAME = 'TripPilot'
_WEBHOOK_HEADERS = (
    ('auth_algo', 'paypal-auth-algo'),
    ('cert_url', 'paypal-cert-url'),
    ('transmission_id', 'paypal-transmission-id'),
    ('transmission_sig', 'paypal-transmission-sig'),
    ('transmission_time', 'paypal-transmission-time'),
)


def _money(cents: Cents) -> JsonDict:
    """Build a PayPal amount object from integer cents."""
    return {'currency_code': CURRENCY, 'value': to_paypal_value(cents)}


def _malformed(status: int, what: str) -> PayPalError:
    """Build the error for a 2xx response that lacks a field the contract needs."""
    return PayPalError(status, 'MALFORMED_RESPONSE', f'response is missing {what}')


def _str_field(body: Mapping[str, Any], key: str, status: int) -> str:
    """Return a required string field of a response body."""
    value = body.get(key)
    if not isinstance(value, str) or not value:
        raise _malformed(status, key)
    return value


def _cents_field(body: Mapping[str, Any], status: int) -> Cents | None:
    """Read `amount.value` as cents, or None when the response has no amount."""
    amount = body.get('amount')
    if not isinstance(amount, Mapping):
        return None
    value = amount.get('value')
    if not isinstance(value, str):
        raise _malformed(status, 'amount.value')
    return from_paypal_value(value)


def _authorization(body: Mapping[str, Any], status: int) -> Authorization:
    """Map a PayPal authorization object to the DTO."""
    amount = _cents_field(body, status)
    if amount is None:
        raise _malformed(status, 'amount')
    create_time = body.get('create_time')
    expiration_time = body.get('expiration_time')
    return Authorization(
        id=_str_field(body, 'id', status),
        status=_str_field(body, 'status', status),
        amount=amount,
        create_time=create_time if isinstance(create_time, str) else None,
        expiration_time=expiration_time if isinstance(expiration_time, str) else None,
    )


def _embedded_authorization(body: Mapping[str, Any], status: int) -> Mapping[str, Any] | None:
    """Return `purchase_units[0].payments.authorizations[0]` of an order body, if present."""
    units = body.get('purchase_units')
    if not isinstance(units, list) or not units or not isinstance(units[0], Mapping):
        return None
    payments = units[0].get('payments')
    if not isinstance(payments, Mapping):
        return None
    authorizations = payments.get('authorizations')
    if not isinstance(authorizations, list) or not authorizations:
        return None
    first = authorizations[0]
    return first if isinstance(first, Mapping) else None


def _webhook(body: Mapping[str, Any], status: int) -> Webhook:
    """Map a PayPal webhook object to the DTO."""
    raw_types = body.get('event_types')
    names = (
        tuple(
            str(item['name']) for item in raw_types if isinstance(item, Mapping) and 'name' in item
        )
        if isinstance(raw_types, list)
        else ()
    )
    return Webhook(
        id=_str_field(body, 'id', status),
        url=_str_field(body, 'url', status),
        event_types=names,
    )


class PayPalClient:
    """PayPal REST client over a shared `httpx.AsyncClient` implementing `PayPalGateway`."""

    def __init__(
        self,
        http: httpx.AsyncClient,
        base_url: str,
        web_base: str,
        client_id: str,
        client_secret: SecretStr,
    ) -> None:
        """Bind the client to an HTTP client, the API and web base URLs, and app credentials."""
        self._http = http
        self._base_url = base_url.rstrip('/')
        self._web_base = web_base.rstrip('/')
        self._auth = (client_id, client_secret.get_secret_value())
        self._tokens = TokenCache(http, base_url, client_id, client_secret)

    # -- transport ---------------------------------------------------------------------------

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: JsonDict | None = None,
        content: bytes | None = None,
        params: Mapping[str, str] | None = None,
        request_id: str | None = None,
    ) -> JsonDict:
        """Send one authorised request, terminating the token and retrying once if rejected.

        `PayPal-Request-Id` is sent only when a `request_id` is passed, and the retry reuses it.
        """
        url = f'{self._base_url}{path}'
        for attempt in (1, 2):
            token = await self._tokens.get()
            headers = {
                'Authorization': f'Bearer {token}',
                'Content-Type': 'application/json',
                'Prefer': 'return=representation',
            }
            if request_id is not None:
                headers['PayPal-Request-Id'] = request_id
            response = await self._http.request(
                method, url, headers=headers, json=json_body, content=content, params=params
            )
            if response.is_success:
                return self._decode_success(response)
            error = PayPalError.from_body(response.status_code, self._decode_error(response))
            rejected = response.status_code == 401 or (
                response.status_code == 403 and error.name == 'NOT_AUTHORIZED'
            )
            if attempt == 1 and rejected:
                await self._tokens.terminate(stale=token)
                continue
            raise error
        raise AssertionError(
            'unreachable: the retry loop always returns or raises'
        )  # pragma: no cover

    @staticmethod
    def _decode_error(response: httpx.Response) -> object:
        """Decode an error body, tolerating empty or non-JSON bodies."""
        try:
            return response.json()
        except ValueError:
            return None

    @staticmethod
    def _decode_success(response: httpx.Response) -> JsonDict:
        """Decode a 2xx body; an empty body (204) becomes an empty dict."""
        if not response.content:
            return {}
        try:
            body = response.json()
        except ValueError as exc:
            raise _malformed(response.status_code, 'a JSON body') from exc
        if not isinstance(body, dict):
            raise _malformed(response.status_code, 'a JSON object')
        return body

    # -- token scopes ------------------------------------------------------------------------

    async def access_token_scopes(self) -> tuple[str, ...]:
        """Return the scopes of the cached token, fetching a token first if none is cached."""
        await self._tokens.get()
        return self._tokens.scopes

    # -- vault -------------------------------------------------------------------------------

    async def create_setup_token(
        self, *, request_id: str, return_url: str, cancel_url: str
    ) -> SetupToken:
        """Create a vault setup token for a buyer to approve."""
        body = await self._request(
            'POST',
            '/v3/vault/setup-tokens',
            request_id=request_id,
            json_body={
                'payment_source': {
                    'paypal': {
                        'usage_type': 'MERCHANT',
                        'usage_pattern': 'IMMEDIATE',
                        'customer_type': 'CONSUMER',
                        'permit_multiple_payment_tokens': False,
                        'experience_context': {
                            'brand_name': BRAND_NAME,
                            'shipping_preference': 'NO_SHIPPING',
                            'return_url': return_url,
                            'cancel_url': cancel_url,
                        },
                    }
                }
            },
        )
        return SetupToken(id=_str_field(body, 'id', 200))

    async def create_payment_token(self, *, request_id: str, setup_token_id: str) -> PaymentToken:
        """Turn an approved setup token into a vaulted payment token."""
        body = await self._request(
            'POST',
            '/v3/vault/payment-tokens',
            request_id=request_id,
            json_body={'payment_source': {'token': {'id': setup_token_id, 'type': 'SETUP_TOKEN'}}},
        )
        customer = body.get('customer')
        source = body.get('payment_source')
        paypal = source.get('paypal') if isinstance(source, Mapping) else None
        paypal = paypal if isinstance(paypal, Mapping) else {}
        customer_id = customer.get('id') if isinstance(customer, Mapping) else None
        payer_id = paypal.get('payer_id')
        email = paypal.get('email_address')
        return PaymentToken(
            id=_str_field(body, 'id', 200),
            customer_id=customer_id if isinstance(customer_id, str) else None,
            payer_id=payer_id if isinstance(payer_id, str) else None,
            email=email if isinstance(email, str) else None,
        )

    async def delete_payment_token(self, *, payment_token_id: str) -> None:
        """Delete a vaulted payment token."""
        await self._request('DELETE', f'/v3/vault/payment-tokens/{quote(payment_token_id)}')

    # -- orders ------------------------------------------------------------------------------

    async def create_order_authorize_vaulted(
        self, *, request_id: str, payment_token_id: str, amount: Cents, description: str
    ) -> VaultedAuthorization:
        """Create an AUTHORIZE order from a vaulted token; the hold exists on return.

        PayPal creates the authorization inside this call, so there is no separate authorize
        step. A response without one (for example a payer-action-required order) raises.
        """
        body = await self._request(
            'POST',
            '/v2/checkout/orders',
            request_id=request_id,
            json_body={
                'intent': 'AUTHORIZE',
                'purchase_units': [{'amount': _money(amount), 'description': description}],
                'payment_source': {'paypal': {'vault_id': payment_token_id}},
            },
        )
        embedded = _embedded_authorization(body, 201)
        order_id = _str_field(body, 'id', 201)
        if embedded is None:
            raise PayPalError(
                201,
                'VAULTED_AUTHORIZATION_MISSING',
                f'order {order_id} has status {body.get("status")!s} and no authorization',
            )
        return VaultedAuthorization(
            order_id=order_id,
            authorization_id=_str_field(embedded, 'id', 201),
            status=_str_field(embedded, 'status', 201),
        )

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
        body = await self._request(
            'POST',
            '/v2/checkout/orders',
            request_id=request_id,
            json_body={
                'intent': 'AUTHORIZE',
                'purchase_units': [{'amount': _money(amount), 'description': description}],
                'payment_source': {
                    'paypal': {
                        'experience_context': {
                            'brand_name': BRAND_NAME,
                            'shipping_preference': 'NO_SHIPPING',
                            'user_action': 'PAY_NOW',
                            'return_url': return_url,
                            'cancel_url': cancel_url,
                        }
                    }
                },
            },
        )
        order_id = _str_field(body, 'id', 201)
        approve_url: str | None = None
        links = body.get('links')
        if isinstance(links, list):
            for link in links:
                if isinstance(link, Mapping) and link.get('rel') in ('payer-action', 'approve'):
                    href = link.get('href')
                    if isinstance(href, str):
                        approve_url = href
                        break
        if approve_url is None:
            approve_url = f'{self._web_base}/checkoutnow?token={quote(order_id)}'
        return Order(id=order_id, status=_str_field(body, 'status', 201), approve_url=approve_url)

    async def authorize_order(self, *, request_id: str, order_id: str) -> Authorization:
        """Authorize an approved order and return the resulting authorization."""
        body = await self._request(
            'POST',
            f'/v2/checkout/orders/{quote(order_id)}/authorize',
            request_id=request_id,
            json_body={},
        )
        embedded = _embedded_authorization(body, 201)
        if embedded is None:
            raise _malformed(201, 'purchase_units[0].payments.authorizations[0]')
        return _authorization(embedded, 201)

    # -- authorizations ----------------------------------------------------------------------

    async def get_authorization(self, authorization_id: str) -> Authorization:
        """Read an authorization (read-only)."""
        body = await self._request('GET', f'/v2/payments/authorizations/{quote(authorization_id)}')
        return _authorization(body, 200)

    async def reauthorize(
        self, *, request_id: str, authorization_id: str, amount: Cents | None
    ) -> Authorization:
        """Reauthorize a hold, optionally for a different amount.

        If PayPal's response omits the amount, the authorization is read back so the DTO is full.
        """
        body = await self._request(
            'POST',
            f'/v2/payments/authorizations/{quote(authorization_id)}/reauthorize',
            request_id=request_id,
            json_body={'amount': _money(amount)} if amount is not None else {},
        )
        if _cents_field(body, 201) is None:
            returned = body.get('id')
            return await self.get_authorization(
                returned if isinstance(returned, str) and returned else authorization_id
            )
        return _authorization(body, 201)

    async def capture_authorization(
        self, *, request_id: str, authorization_id: str, amount: Cents, final_capture: bool
    ) -> Capture:
        """Capture `amount` against an authorization; `final_capture` releases the remainder."""
        body = await self._request(
            'POST',
            f'/v2/payments/authorizations/{quote(authorization_id)}/capture',
            request_id=request_id,
            json_body={'amount': _money(amount), 'final_capture': final_capture},
        )
        return Capture(
            id=_str_field(body, 'id', 201),
            status=_str_field(body, 'status', 201),
            amount=_cents_field(body, 201) or amount,
        )

    async def void_authorization(self, *, request_id: str, authorization_id: str) -> Authorization:
        """Void an authorization, then read it back so the caller sees its final state."""
        await self._request(
            'POST',
            f'/v2/payments/authorizations/{quote(authorization_id)}/void',
            request_id=request_id,
            json_body={},
        )
        return await self.get_authorization(authorization_id)

    # -- webhooks ----------------------------------------------------------------------------

    async def verify_webhook_signature(
        self, *, headers: Mapping[str, str], raw_body: bytes, webhook_id: str
    ) -> bool:
        """Ask PayPal whether a delivery is genuine, posting the raw event bytes unmodified.

        The event must be sent back exactly as received, so the raw body is spliced into the
        request as bytes rather than parsed and re-serialised. A delivery missing any of the
        `paypal-*` signature headers is not genuine and returns False without calling PayPal.
        """
        lowered = {key.lower(): value for key, value in headers.items()}
        fields: dict[str, str] = {}
        for field, header in _WEBHOOK_HEADERS:
            value = lowered.get(header)
            if not value:
                return False
            fields[field] = value
        fields['webhook_id'] = webhook_id
        head = json.dumps(fields).removesuffix('}')
        content = head.encode() + b', "webhook_event": ' + raw_body + b'}'
        body = await self._request(
            'POST', '/v1/notifications/verify-webhook-signature', content=content
        )
        return body.get('verification_status') == 'SUCCESS'

    async def create_webhook(self, *, url: str, event_types: Sequence[str]) -> Webhook:
        """Register a webhook endpoint for the given event types."""
        body = await self._request(
            'POST',
            '/v1/notifications/webhooks',
            json_body={'url': url, 'event_types': [{'name': name} for name in event_types]},
        )
        return _webhook(body, 201)

    async def list_webhooks(self) -> tuple[Webhook, ...]:
        """List the webhooks registered for the app."""
        body = await self._request('GET', '/v1/notifications/webhooks')
        raw = body.get('webhooks')
        items = raw if isinstance(raw, list) else []
        return tuple(_webhook(item, 200) for item in items if isinstance(item, Mapping))

    async def list_webhook_event_types(self) -> tuple[str, ...]:
        """List the names of every webhook event type PayPal offers."""
        body = await self._request('GET', '/v1/notifications/webhooks-event-types')
        raw = body.get('event_types')
        items = raw if isinstance(raw, list) else []
        return tuple(
            str(item['name']) for item in items if isinstance(item, Mapping) and 'name' in item
        )

    # -- Log in with PayPal ------------------------------------------------------------------

    async def exchange_login_code(self, *, code: str, redirect_uri: str) -> LoginTokens:
        """Exchange a Log in with PayPal authorization code for tokens (Basic app auth)."""
        response = await self._http.post(
            f'{self._base_url}/v1/oauth2/token',
            auth=self._auth,
            data={'grant_type': 'authorization_code', 'code': code, 'redirect_uri': redirect_uri},
        )
        if not response.is_success:
            raise PayPalError.from_body(response.status_code, self._decode_error(response))
        body = self._decode_success(response)
        return LoginTokens(access_token=SecretStr(_str_field(body, 'access_token', 200)))

    async def get_userinfo(self, *, access_token: SecretStr, schema: str) -> UserInfo:
        """Fetch identity claims with the user's own bearer token (not the app token)."""
        response = await self._http.get(
            f'{self._base_url}/v1/identity/oauth2/userinfo',
            params={'schema': schema},
            headers={
                'Authorization': f'Bearer {access_token.get_secret_value()}',
                'Content-Type': 'application/json',
            },
        )
        if not response.is_success:
            raise PayPalError.from_body(response.status_code, self._decode_error(response))
        return UserInfo(claims=self._decode_success(response))

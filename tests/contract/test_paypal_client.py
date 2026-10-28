"""Contract tests for the typed PayPal httpx client and token cache, with respx."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Iterator

import httpx
import pytest
import respx
from pydantic import SecretStr

from trippilot.contracts.money import Cents
from trippilot.contracts.paypal import PayPalError
from trippilot.payments.client import PayPalClient
from trippilot.payments.token_cache import TokenCache

BASE = 'https://api-m.sandbox.paypal.com'
WEB = 'https://www.sandbox.paypal.com'
VAULT_SCOPE = 'https://uri.paypal.com/services/vault/payment-tokens/readwrite'


def token_response(token: str = 'tok-1', expires_in: int = 32400) -> httpx.Response:
    """Build a client-credentials token response."""
    return httpx.Response(
        200,
        json={
            'access_token': token,
            'token_type': 'Bearer',
            'expires_in': expires_in,
            'scope': f'openid {VAULT_SCOPE}',
        },
    )


@pytest.fixture
def router() -> Iterator[respx.MockRouter]:
    """A respx router that mocks every httpx request made in the test."""
    with respx.mock(assert_all_called=False) as mock:
        yield mock


@pytest.fixture
async def http() -> AsyncIterator[httpx.AsyncClient]:
    """A real httpx.AsyncClient whose transport respx patches."""
    async with httpx.AsyncClient() as client:
        yield client


def make_client(http: httpx.AsyncClient) -> PayPalClient:
    """Build a client against the sandbox base URLs with throwaway credentials."""
    return PayPalClient(http, BASE, WEB, 'client-id', SecretStr('client-secret'))


PAYMENT_TOKEN_BODY = {
    'id': 'PT-1',
    'customer': {'id': 'CUST-1'},
    'payment_source': {'paypal': {'payer_id': 'PAYER-1', 'email_address': 'a@example.com'}},
}


async def test_mutating_call_sends_request_id_and_prefer_header(
    router: respx.MockRouter, http: httpx.AsyncClient
) -> None:
    router.post(f'{BASE}/v1/oauth2/token').mock(return_value=token_response())
    route = router.post(f'{BASE}/v3/vault/payment-tokens').mock(
        return_value=httpx.Response(201, json=PAYMENT_TOKEN_BODY)
    )

    token = await make_client(http).create_payment_token(request_id='req-1', setup_token_id='ST-1')

    request = route.calls.last.request
    assert request.headers['PayPal-Request-Id'] == 'req-1'
    assert request.headers['Prefer'] == 'return=representation'
    assert request.headers['Authorization'] == 'Bearer tok-1'
    assert (token.id, token.customer_id, token.payer_id) == ('PT-1', 'CUST-1', 'PAYER-1')


async def test_not_authorized_terminates_token_and_retries_once_with_same_request_id(
    router: respx.MockRouter, http: httpx.AsyncClient
) -> None:
    token_route = router.post(f'{BASE}/v1/oauth2/token').mock(
        side_effect=[token_response('tok-1'), token_response('tok-2')]
    )
    terminate_route = router.post(f'{BASE}/v1/oauth2/token/terminate').mock(
        return_value=httpx.Response(200)
    )
    route = router.post(f'{BASE}/v3/vault/payment-tokens').mock(
        side_effect=[
            httpx.Response(403, json={'name': 'NOT_AUTHORIZED', 'message': 'insufficient'}),
            httpx.Response(201, json=PAYMENT_TOKEN_BODY),
        ]
    )

    token = await make_client(http).create_payment_token(request_id='req-1', setup_token_id='ST-1')

    assert token.id == 'PT-1'
    assert terminate_route.call_count == 1
    assert token_route.call_count == 2
    first, second = (call.request for call in route.calls)
    assert first.headers['PayPal-Request-Id'] == second.headers['PayPal-Request-Id'] == 'req-1'
    assert first.headers['Authorization'] == 'Bearer tok-1'
    assert second.headers['Authorization'] == 'Bearer tok-2'


async def test_two_consecutive_not_authorized_responses_raise(
    router: respx.MockRouter, http: httpx.AsyncClient
) -> None:
    router.post(f'{BASE}/v1/oauth2/token').mock(
        side_effect=[token_response('tok-1'), token_response('tok-2')]
    )
    terminate_route = router.post(f'{BASE}/v1/oauth2/token/terminate').mock(
        return_value=httpx.Response(200)
    )
    route = router.post(f'{BASE}/v3/vault/payment-tokens').mock(
        return_value=httpx.Response(403, json={'name': 'NOT_AUTHORIZED', 'debug_id': 'dbg-1'})
    )

    with pytest.raises(PayPalError) as excinfo:
        await make_client(http).create_payment_token(request_id='req-1', setup_token_id='ST-1')

    assert excinfo.value.status == 403
    assert excinfo.value.name == 'NOT_AUTHORIZED'
    assert route.call_count == 2
    assert terminate_route.call_count == 1


async def test_capture_sends_cents_as_two_decimal_string_and_final_capture(
    router: respx.MockRouter, http: httpx.AsyncClient
) -> None:
    router.post(f'{BASE}/v1/oauth2/token').mock(return_value=token_response())
    route = router.post(f'{BASE}/v2/payments/authorizations/AUTH-1/capture').mock(
        return_value=httpx.Response(
            201,
            json={
                'id': 'CAP-1',
                'status': 'COMPLETED',
                'amount': {'currency_code': 'USD', 'value': '0.50'},
            },
        )
    )

    capture = await make_client(http).capture_authorization(
        request_id='req-cap', authorization_id='AUTH-1', amount=Cents(50), final_capture=True
    )

    assert json.loads(route.calls.last.request.content) == {
        'amount': {'currency_code': 'USD', 'value': '0.50'},
        'final_capture': True,
    }
    assert route.calls.last.request.headers['PayPal-Request-Id'] == 'req-cap'
    assert (capture.id, capture.status, capture.amount) == ('CAP-1', 'COMPLETED', 50)


async def test_vaulted_order_maps_embedded_authorization_without_second_call(
    router: respx.MockRouter, http: httpx.AsyncClient
) -> None:
    router.post(f'{BASE}/v1/oauth2/token').mock(return_value=token_response())
    order_route = router.post(f'{BASE}/v2/checkout/orders').mock(
        return_value=httpx.Response(
            201,
            json={
                'id': 'ORDER-1',
                'status': 'COMPLETED',
                'purchase_units': [
                    {'payments': {'authorizations': [{'id': 'AUTH-9', 'status': 'CREATED'}]}}
                ],
            },
        )
    )
    authorize_route = router.post(f'{BASE}/v2/checkout/orders/ORDER-1/authorize').mock(
        return_value=httpx.Response(500)
    )

    result = await make_client(http).create_order_authorize_vaulted(
        request_id='req-hold', payment_token_id='PT-1', amount=Cents(23000), description='Trip'
    )

    assert (result.order_id, result.authorization_id, result.status) == (
        'ORDER-1',
        'AUTH-9',
        'CREATED',
    )
    assert order_route.call_count == 1
    assert authorize_route.call_count == 0
    sent = json.loads(order_route.calls.last.request.content)
    assert sent['intent'] == 'AUTHORIZE'
    assert sent['purchase_units'][0]['amount'] == {'currency_code': 'USD', 'value': '230.00'}
    assert sent['payment_source']['paypal']['vault_id'] == 'PT-1'


async def test_token_cache_reuses_token_until_sixty_seconds_before_expiry_and_records_scopes(
    router: respx.MockRouter, http: httpx.AsyncClient
) -> None:
    now = [1000.0]
    token_route = router.post(f'{BASE}/v1/oauth2/token').mock(
        side_effect=[
            token_response('tok-1', expires_in=300),
            token_response('tok-2', expires_in=300),
        ]
    )
    cache = TokenCache(http, BASE, 'client-id', SecretStr('client-secret'), clock=lambda: now[0])

    assert await cache.get() == 'tok-1'
    now[0] += 239  # 61 seconds of life left: still reused
    assert await cache.get() == 'tok-1'
    assert token_route.call_count == 1
    now[0] += 2  # 59 seconds left: inside the margin, refreshed
    assert await cache.get() == 'tok-2'
    assert token_route.call_count == 2
    assert VAULT_SCOPE in cache.scopes


async def test_token_cache_fetches_once_for_concurrent_callers(
    router: respx.MockRouter, http: httpx.AsyncClient
) -> None:
    token_route = router.post(f'{BASE}/v1/oauth2/token').mock(return_value=token_response())
    cache = TokenCache(http, BASE, 'client-id', SecretStr('client-secret'))

    tokens = await asyncio.gather(*(cache.get() for _ in range(5)))

    assert set(tokens) == {'tok-1'}
    assert token_route.call_count == 1


async def test_plain_403_is_not_retried_and_summary_hides_the_raw_body(
    router: respx.MockRouter, http: httpx.AsyncClient
) -> None:
    router.post(f'{BASE}/v1/oauth2/token').mock(return_value=token_response())
    terminate_route = router.post(f'{BASE}/v1/oauth2/token/terminate').mock(
        return_value=httpx.Response(200)
    )
    route = router.post(f'{BASE}/v3/vault/payment-tokens').mock(
        return_value=httpx.Response(
            403,
            json={
                'name': 'PERMISSION_DENIED',
                'message': 'nope',
                'debug_id': 'dbg-2',
                'details': [{'issue': 'PAYEE_ACCOUNT_RESTRICTED', 'value': 'secret-echo'}],
                'secret_field': 'must-not-leak',
            },
        )
    )

    with pytest.raises(PayPalError) as excinfo:
        await make_client(http).create_payment_token(request_id='req-1', setup_token_id='ST-1')

    assert route.call_count == 1
    assert terminate_route.call_count == 0
    summary = excinfo.value.summary()
    assert summary['debug_id'] == 'dbg-2'
    assert summary['issues'] == ['PAYEE_ACCOUNT_RESTRICTED']
    assert 'must-not-leak' not in str(summary)
    assert 'secret-echo' not in str(summary)


async def test_401_also_terminates_and_retries_once(
    router: respx.MockRouter, http: httpx.AsyncClient
) -> None:
    router.post(f'{BASE}/v1/oauth2/token').mock(
        side_effect=[token_response('tok-1'), token_response('tok-2')]
    )
    terminate_route = router.post(f'{BASE}/v1/oauth2/token/terminate').mock(
        return_value=httpx.Response(200)
    )
    router.get(f'{BASE}/v2/payments/authorizations/AUTH-1').mock(
        side_effect=[
            httpx.Response(401, json={'error': 'invalid_token'}),
            httpx.Response(
                200,
                json={
                    'id': 'AUTH-1',
                    'status': 'CREATED',
                    'amount': {'currency_code': 'USD', 'value': '5.00'},
                    'create_time': '2026-10-28T05:00:00Z',
                    'expiration_time': '2026-11-26T05:00:00Z',
                },
            ),
        ]
    )

    auth = await make_client(http).get_authorization('AUTH-1')

    assert terminate_route.call_count == 1
    assert (auth.id, auth.status, auth.amount) == ('AUTH-1', 'CREATED', 500)
    assert auth.expiration_time == '2026-11-26T05:00:00Z'


async def test_get_calls_carry_no_request_id(
    router: respx.MockRouter, http: httpx.AsyncClient
) -> None:
    router.post(f'{BASE}/v1/oauth2/token').mock(return_value=token_response())
    route = router.get(f'{BASE}/v1/notifications/webhooks-event-types').mock(
        return_value=httpx.Response(
            200, json={'event_types': [{'name': 'PAYMENT.AUTHORIZATION.CREATED'}, {'name': 'X'}]}
        )
    )

    names = await make_client(http).list_webhook_event_types()

    assert names == ('PAYMENT.AUTHORIZATION.CREATED', 'X')
    assert 'PayPal-Request-Id' not in route.calls.last.request.headers


async def test_access_token_scopes_reports_the_vault_scope(
    router: respx.MockRouter, http: httpx.AsyncClient
) -> None:
    router.post(f'{BASE}/v1/oauth2/token').mock(return_value=token_response())

    scopes = await make_client(http).access_token_scopes()

    assert VAULT_SCOPE in scopes


async def test_void_posts_then_reads_the_authorization_back(
    router: respx.MockRouter, http: httpx.AsyncClient
) -> None:
    router.post(f'{BASE}/v1/oauth2/token').mock(return_value=token_response())
    void_route = router.post(f'{BASE}/v2/payments/authorizations/AUTH-1/void').mock(
        return_value=httpx.Response(204)
    )
    router.get(f'{BASE}/v2/payments/authorizations/AUTH-1').mock(
        return_value=httpx.Response(
            200,
            json={
                'id': 'AUTH-1',
                'status': 'VOIDED',
                'amount': {'currency_code': 'USD', 'value': '1.00'},
            },
        )
    )

    auth = await make_client(http).void_authorization(
        request_id='req-void', authorization_id='AUTH-1'
    )

    assert void_route.calls.last.request.headers['PayPal-Request-Id'] == 'req-void'
    assert auth.status == 'VOIDED'


async def test_reauthorize_sends_optional_amount(
    router: respx.MockRouter, http: httpx.AsyncClient
) -> None:
    router.post(f'{BASE}/v1/oauth2/token').mock(return_value=token_response())
    route = router.post(f'{BASE}/v2/payments/authorizations/AUTH-1/reauthorize').mock(
        return_value=httpx.Response(
            201,
            json={
                'id': 'AUTH-1',
                'status': 'CREATED',
                'amount': {'currency_code': 'USD', 'value': '2.00'},
            },
        )
    )
    client = make_client(http)

    with_amount = await client.reauthorize(
        request_id='req-re-1', authorization_id='AUTH-1', amount=Cents(200)
    )
    await client.reauthorize(request_id='req-re-2', authorization_id='AUTH-1', amount=None)

    first, second = (call.request for call in route.calls)
    assert json.loads(first.content) == {'amount': {'currency_code': 'USD', 'value': '2.00'}}
    assert json.loads(second.content) == {}
    assert with_amount.amount == 200


async def test_webhook_verification_splices_the_raw_body_unmodified(
    router: respx.MockRouter, http: httpx.AsyncClient
) -> None:
    router.post(f'{BASE}/v1/oauth2/token').mock(return_value=token_response())
    route = router.post(f'{BASE}/v1/notifications/verify-webhook-signature').mock(
        side_effect=[
            httpx.Response(200, json={'verification_status': 'SUCCESS'}),
            httpx.Response(200, json={'verification_status': 'FAILURE'}),
        ]
    )
    raw = b'{"id":  "WH-1",   "event_type":"PAYMENT.AUTHORIZATION.CREATED"}'
    headers = {
        'PAYPAL-AUTH-ALGO': 'SHA256withRSA',
        'PAYPAL-CERT-URL': 'https://api.sandbox.paypal.com/cert.pem',
        'PAYPAL-TRANSMISSION-ID': 'tx-1',
        'PAYPAL-TRANSMISSION-SIG': 'sig',
        'PAYPAL-TRANSMISSION-TIME': '2026-10-28T05:00:00Z',
    }
    client = make_client(http)

    assert await client.verify_webhook_signature(headers=headers, raw_body=raw, webhook_id='WHK-1')
    assert not await client.verify_webhook_signature(
        headers=headers, raw_body=raw, webhook_id='WHK-1'
    )

    sent = route.calls[0].request.content
    assert raw in sent
    decoded = json.loads(sent)
    assert decoded['webhook_id'] == 'WHK-1'
    assert decoded['transmission_id'] == 'tx-1'
    assert decoded['webhook_event'] == {
        'id': 'WH-1',
        'event_type': 'PAYMENT.AUTHORIZATION.CREATED',
    }


async def test_webhook_verification_without_signature_headers_is_false_and_makes_no_call(
    router: respx.MockRouter, http: httpx.AsyncClient
) -> None:
    token_route = router.post(f'{BASE}/v1/oauth2/token').mock(return_value=token_response())

    verdict = await make_client(http).verify_webhook_signature(
        headers={}, raw_body=b'{}', webhook_id='WHK-1'
    )

    assert verdict is False
    assert token_route.call_count == 0


async def test_login_code_exchange_uses_basic_auth_and_userinfo_uses_the_user_token(
    router: respx.MockRouter, http: httpx.AsyncClient
) -> None:
    token_route = router.post(f'{BASE}/v1/oauth2/token').mock(
        return_value=httpx.Response(200, json={'access_token': 'user-token', 'expires_in': 100})
    )
    info_route = router.get(f'{BASE}/v1/identity/oauth2/userinfo').mock(
        return_value=httpx.Response(
            200,
            json={'user_id': 'https://paypal/u/1', 'name': 'Ada Lovelace', 'given_name': 'Ada'},
        )
    )
    client = make_client(http)

    tokens = await client.exchange_login_code(code='the-code', redirect_uri='https://app/cb')
    info = await client.get_userinfo(access_token=tokens.access_token, schema='openid')

    request = token_route.calls.last.request
    assert request.headers['Authorization'].startswith('Basic ')
    assert b'grant_type=authorization_code' in request.content
    assert b'code=the-code' in request.content
    assert tokens.access_token.get_secret_value() == 'user-token'
    assert 'user-token' not in repr(tokens)
    assert info_route.calls.last.request.headers['Authorization'] == 'Bearer user-token'
    assert info_route.calls.last.request.url.params['schema'] == 'openid'
    assert (info.subject, info.name, info.given_name) == (
        'https://paypal/u/1',
        'Ada Lovelace',
        'Ada',
    )
    assert token_route.call_count == 1  # no client-credentials token was fetched


async def test_vaulted_order_without_authorization_raises_a_typed_error(
    router: respx.MockRouter, http: httpx.AsyncClient
) -> None:
    router.post(f'{BASE}/v1/oauth2/token').mock(return_value=token_response())
    router.post(f'{BASE}/v2/checkout/orders').mock(
        return_value=httpx.Response(
            201, json={'id': 'ORDER-2', 'status': 'PAYER_ACTION_REQUIRED', 'purchase_units': [{}]}
        )
    )

    with pytest.raises(PayPalError) as excinfo:
        await make_client(http).create_order_authorize_vaulted(
            request_id='req-hold', payment_token_id='PT-1', amount=Cents(100), description='Trip'
        )

    assert excinfo.value.name == 'VAULTED_AUTHORIZATION_MISSING'

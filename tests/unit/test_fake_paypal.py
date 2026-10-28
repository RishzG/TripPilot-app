"""Tests for FakePayPal and the get_paypal_gateway dependency."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from pydantic import SecretStr
from trippilot.payments.fake import FakePayPal

from trippilot.contracts.money import Cents
from trippilot.contracts.paypal import PayPalError, PayPalGateway
from trippilot.payments import aclose_paypal_gateway, get_paypal_gateway, reset_paypal_gateway
from trippilot.payments.client import PayPalClient
from trippilot.settings import get_settings


@pytest.fixture
async def clean_gateway() -> AsyncIterator[None]:
    """Clear the cached settings and process-wide gateway around a test."""
    get_settings.cache_clear()
    reset_paypal_gateway()
    yield
    await aclose_paypal_gateway()
    reset_paypal_gateway()
    get_settings.cache_clear()


async def vaulted_token(fake: FakePayPal) -> str:
    """Create a saved PayPal on the fake and return its payment token id."""
    setup = await fake.create_setup_token(request_id='s-1', return_url='r', cancel_url='c')
    token = await fake.create_payment_token(request_id='p-1', setup_token_id=setup.id)
    return token.id


async def test_fake_satisfies_the_gateway_protocol_statically() -> None:
    gateway: PayPalGateway = FakePayPal()
    assert await gateway.access_token_scopes()


async def test_vaulted_hold_with_the_same_request_id_returns_the_same_authorization() -> None:
    fake = FakePayPal()
    token_id = await vaulted_token(fake)
    calls_before = len(fake.calls)

    first = await fake.create_order_authorize_vaulted(
        request_id='hold-1', payment_token_id=token_id, amount=Cents(23000), description='Trip'
    )
    second = await fake.create_order_authorize_vaulted(
        request_id='hold-1', payment_token_id=token_id, amount=Cents(99999), description='Other'
    )

    assert first == second
    assert first.authorization_id == 'FAKE-AUTH-0001'
    assert len(fake.calls) - calls_before == 1
    assert (await fake.get_authorization(first.authorization_id)).amount == 23000


async def test_a_different_request_id_creates_a_new_authorization() -> None:
    fake = FakePayPal()
    token_id = await vaulted_token(fake)

    one = await fake.create_order_authorize_vaulted(
        request_id='hold-1', payment_token_id=token_id, amount=Cents(100), description='a'
    )
    two = await fake.create_order_authorize_vaulted(
        request_id='hold-2', payment_token_id=token_id, amount=Cents(100), description='a'
    )

    assert (one.authorization_id, two.authorization_id) == ('FAKE-AUTH-0001', 'FAKE-AUTH-0002')


async def test_fail_next_fails_only_the_next_call_of_that_method() -> None:
    fake = FakePayPal()
    token_id = await vaulted_token(fake)
    hold = await fake.create_order_authorize_vaulted(
        request_id='hold-1', payment_token_id=token_id, amount=Cents(500), description='a'
    )
    fake.fail_next('capture_authorization', PayPalError(500, 'INTERNAL_SERVER_ERROR'))

    with pytest.raises(PayPalError):
        await fake.capture_authorization(
            request_id='cap-1',
            authorization_id=hold.authorization_id,
            amount=Cents(100),
            final_capture=False,
        )
    capture = await fake.capture_authorization(
        request_id='cap-1',
        authorization_id=hold.authorization_id,
        amount=Cents(100),
        final_capture=False,
    )

    assert capture.amount == 100
    # the failed attempt stored nothing, so the same request id ran for real the second time
    assert (await fake.get_authorization(hold.authorization_id)).status == 'PARTIALLY_CAPTURED'


async def test_fail_next_rejects_an_unknown_method_name() -> None:
    with pytest.raises(ValueError, match='not_a_method'):
        FakePayPal().fail_next('not_a_method', PayPalError(500))


async def test_authorization_state_machine_capture_void_and_illegal_moves() -> None:
    fake = FakePayPal()
    token_id = await vaulted_token(fake)
    a = await fake.create_order_authorize_vaulted(
        request_id='h-a', payment_token_id=token_id, amount=Cents(1000), description='a'
    )
    b = await fake.create_order_authorize_vaulted(
        request_id='h-b', payment_token_id=token_id, amount=Cents(1000), description='b'
    )

    final = await fake.capture_authorization(
        request_id='c-a', authorization_id=a.authorization_id, amount=Cents(50), final_capture=True
    )
    voided = await fake.void_authorization(request_id='v-b', authorization_id=b.authorization_id)

    assert final.amount == 50
    assert (await fake.get_authorization(a.authorization_id)).status == 'CAPTURED'
    assert voided.status == 'VOIDED'
    with pytest.raises(PayPalError):  # capture after final capture
        await fake.capture_authorization(
            request_id='c-a2',
            authorization_id=a.authorization_id,
            amount=Cents(1),
            final_capture=True,
        )
    with pytest.raises(PayPalError):  # capture after void
        await fake.capture_authorization(
            request_id='c-b',
            authorization_id=b.authorization_id,
            amount=Cents(1),
            final_capture=True,
        )
    with pytest.raises(PayPalError):  # void after capture
        await fake.void_authorization(request_id='v-a', authorization_id=a.authorization_id)


async def test_capture_cannot_exceed_the_authorized_amount() -> None:
    fake = FakePayPal()
    token_id = await vaulted_token(fake)
    hold = await fake.create_order_authorize_vaulted(
        request_id='h', payment_token_id=token_id, amount=Cents(1000), description='a'
    )

    with pytest.raises(PayPalError) as excinfo:
        await fake.capture_authorization(
            request_id='c',
            authorization_id=hold.authorization_id,
            amount=Cents(1001),
            final_capture=True,
        )

    assert excinfo.value.name == 'AMOUNT_EXCEEDS_AUTHORIZATION'


async def test_deleted_payment_token_can_no_longer_hold() -> None:
    fake = FakePayPal()
    token_id = await vaulted_token(fake)
    await fake.delete_payment_token(payment_token_id=token_id)

    with pytest.raises(PayPalError):
        await fake.create_order_authorize_vaulted(
            request_id='h', payment_token_id=token_id, amount=Cents(100), description='a'
        )


async def test_browser_order_flow_authorize_after_approval() -> None:
    fake = FakePayPal()

    order = await fake.create_order_authorize(
        request_id='o-1', amount=Cents(700), description='a', return_url='r', cancel_url='c'
    )
    auth = await fake.authorize_order(request_id='a-1', order_id=order.id)

    assert order.approve_url is not None
    assert (auth.status, auth.amount) == ('CREATED', 700)


async def test_reauthorize_keeps_a_created_hold_and_rejects_a_voided_one() -> None:
    fake = FakePayPal()
    token_id = await vaulted_token(fake)
    hold = await fake.create_order_authorize_vaulted(
        request_id='h', payment_token_id=token_id, amount=Cents(1000), description='a'
    )

    again = await fake.reauthorize(
        request_id='r-1', authorization_id=hold.authorization_id, amount=Cents(1200)
    )
    await fake.void_authorization(request_id='v', authorization_id=hold.authorization_id)

    assert (again.status, again.amount) == ('CREATED', 1200)
    with pytest.raises(PayPalError):
        await fake.reauthorize(
            request_id='r-2', authorization_id=hold.authorization_id, amount=None
        )


async def test_registered_login_returns_its_claims_and_unknown_codes_raise() -> None:
    fake = FakePayPal()
    fake.register_login('code-1', {'user_id': 'u-1', 'name': 'Ada Lovelace', 'given_name': 'Ada'})

    tokens = await fake.exchange_login_code(code='code-1', redirect_uri='https://app/cb')
    info = await fake.get_userinfo(access_token=tokens.access_token, schema='openid')

    assert (info.subject, info.name, info.given_name) == ('u-1', 'Ada Lovelace', 'Ada')
    with pytest.raises(PayPalError):
        await fake.exchange_login_code(code='nope', redirect_uri='https://app/cb')
    with pytest.raises(PayPalError):  # a code is single use, like PayPal's
        await fake.exchange_login_code(code='code-1', redirect_uri='https://app/cb')
    with pytest.raises(PayPalError):
        await fake.get_userinfo(access_token=SecretStr('bogus'), schema='openid')


async def test_webhook_verdict_defaults_true_and_is_configurable() -> None:
    fake = FakePayPal()
    assert await fake.verify_webhook_signature(headers={}, raw_body=b'{}', webhook_id='w')

    fake.webhook_verdict = False

    assert not await fake.verify_webhook_signature(headers={}, raw_body=b'{}', webhook_id='w')


async def test_webhook_registration_and_event_type_listing() -> None:
    fake = FakePayPal()

    created = await fake.create_webhook(url='https://app/hook', event_types=['A', 'B'])

    assert (await fake.list_webhooks()) == (created,)
    assert created.event_types == ('A', 'B')
    assert await fake.list_webhook_event_types()


@pytest.mark.usefixtures('clean_gateway')
async def test_get_paypal_gateway_returns_the_fake_in_fake_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv('PAYPAL_MODE', 'fake')

    gateway = get_paypal_gateway()

    assert isinstance(gateway, FakePayPal)
    assert get_paypal_gateway() is gateway


@pytest.mark.usefixtures('clean_gateway')
async def test_get_paypal_gateway_returns_the_client_in_sandbox_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv('PAYPAL_MODE', 'sandbox')
    monkeypatch.setenv('PAYPAL_CLIENT_ID', 'test-client-id')
    monkeypatch.setenv('PAYPAL_CLIENT_SECRET', 'test-client-secret')

    gateway = get_paypal_gateway()

    assert isinstance(gateway, PayPalClient)
    assert get_paypal_gateway() is gateway


@pytest.mark.usefixtures('clean_gateway')
async def test_reset_paypal_gateway_builds_a_fresh_instance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv('PAYPAL_MODE', 'fake')
    first = get_paypal_gateway()

    reset_paypal_gateway()

    assert get_paypal_gateway() is not first

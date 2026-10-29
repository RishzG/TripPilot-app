"""Unit tests for scripts/spikes/register_webhook.py (01-13), against FakePayPal only.

The script is loaded by path; its results file is redirected into pytest's tmp_path, so nothing
here touches PayPal, the network or the real scripts/spikes/results directory.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, cast

import pytest

from trippilot.contracts.paypal import PayPalError, Webhook
from trippilot.payments.client import PayPalClient
from trippilot.payments.fake import FakePayPal

SCRIPT = Path(__file__).resolve().parents[2] / 'scripts' / 'spikes' / 'register_webhook.py'
URL = 'https://staging.example.test/api/paypal/webhooks'


@pytest.fixture
def script(tmp_path: Path) -> ModuleType:
    """Load the script as a module with its results file pointed at tmp_path."""
    spec = importlib.util.spec_from_file_location('register_webhook_under_test', SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    module.__dict__['RESULTS_FILE'] = tmp_path / 'results' / 'webhook_registration.json'
    return module


async def _register(script: ModuleType, fake: FakePayPal, url: str = URL) -> int:
    code: int = await script._register(cast(PayPalClient, fake), url)
    return code


def _results(script: ModuleType) -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads(script.RESULTS_FILE.read_text(encoding='utf-8'))
    return loaded


async def test_it_creates_one_webhook_with_only_the_confirmed_names(
    script: ModuleType, capsys: pytest.CaptureFixture[str]
) -> None:
    fake = FakePayPal()

    code = await _register(script, fake)

    assert code == 0
    hooks = await fake.list_webhooks()
    assert [hook.url for hook in hooks] == [URL]
    offered = set(fake.event_types)
    wanted = set(script.RESEARCH_EVENT_NAMES)
    assert set(hooks[0].event_types) == offered & wanted
    out = capsys.readouterr().out
    assert f'webhook_id: {hooks[0].id}' in out
    assert 'confirmed: PAYMENT.AUTHORIZATION.CREATED' in out
    assert 'NOT offered: PAYMENT.PAYOUTSBATCH.SUCCESS' in out
    results = _results(script)
    assert results['webhook_id'] == hooks[0].id
    assert results['reused_existing_webhook'] is False
    assert 'PAYMENT.PAYOUTSBATCH.SUCCESS' in results['missing_event_names']
    assert results['subscribed_event_names'] == list(hooks[0].event_types)


async def test_running_it_again_reuses_the_webhook_and_creates_nothing(
    script: ModuleType,
) -> None:
    fake = FakePayPal()
    assert await _register(script, fake) == 0
    first_id = _results(script)['webhook_id']

    assert await _register(script, fake) == 0

    assert len(await fake.list_webhooks()) == 1
    assert sum(1 for name, _ in fake.calls if name == 'create_webhook') == 1
    results = _results(script)
    assert results['webhook_id'] == first_id
    assert results['reused_existing_webhook'] is True


async def test_a_different_url_gets_its_own_webhook(script: ModuleType) -> None:
    fake = FakePayPal()
    await fake.create_webhook(url='https://other.example.test/api/paypal/webhooks', event_types=())

    assert await _register(script, fake) == 0

    assert len(await fake.list_webhooks()) == 2
    assert _results(script)['other_webhooks_on_this_app'] == 1


async def test_a_duplicate_url_error_from_paypal_is_resolved_by_reusing_the_webhook(
    script: ModuleType,
) -> None:
    class RacyPayPal(FakePayPal):
        """The first listing misses a webhook that PayPal then refuses to create twice."""

        def __init__(self) -> None:
            super().__init__()
            self.listings = 0

        async def list_webhooks(self) -> tuple[Webhook, ...]:
            self.listings += 1
            if self.listings == 1:
                return ()
            return (Webhook('WH-EXISTING', URL, ('PAYMENT.AUTHORIZATION.CREATED',)),)

    fake = RacyPayPal()
    fake.fail_next('create_webhook', PayPalError(400, 'WEBHOOK_URL_ALREADY_EXISTS', 'exists'))

    assert await _register(script, fake) == 0

    results = _results(script)
    assert results['webhook_id'] == 'WH-EXISTING'
    assert results['reused_existing_webhook'] is True
    assert results['confirmed_but_not_subscribed']  # reported, never changed


async def test_it_refuses_to_register_when_no_research_name_exists(script: ModuleType) -> None:
    fake = FakePayPal()
    fake.event_types = ('SOME.OTHER.EVENT',)

    assert await _register(script, fake) == 1

    assert await fake.list_webhooks() == ()
    assert not script.RESULTS_FILE.exists()


async def test_the_results_file_holds_names_and_ids_only(script: ModuleType) -> None:
    assert await _register(script, FakePayPal()) == 0

    text = script.RESULTS_FILE.read_text(encoding='utf-8').lower()
    for forbidden in ('secret', 'token', 'password', 'authorization:'):
        assert forbidden not in text.replace('payment-token', '')


@pytest.mark.parametrize(
    ('url', 'fragment'),
    [
        ('http://staging.example.test/api/paypal/webhooks', 'https'),
        ('https://localhost/api/paypal/webhooks', 'localhost'),
        ('https://staging.example.test/api/paypal/webhook', 'path'),
        ('https://staging.example.test/api/paypal/webhooks?x=1', 'path'),
        ('not a url', 'https'),
    ],
)
def test_urls_that_could_never_receive_a_delivery_are_refused(
    script: ModuleType, url: str, fragment: str
) -> None:
    problem = script._url_problem(url)

    assert problem is not None
    assert fragment in problem


def test_the_expected_staging_url_is_accepted(script: ModuleType) -> None:
    assert script._url_problem(URL) is None

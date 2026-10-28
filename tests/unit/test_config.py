"""Settings contract and log redaction tests (PLAT-01, PLAT-04)."""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from typing import Any

import pytest
import structlog
from pydantic import ValidationError

from trippilot.log_config import configure_logging
from trippilot.settings import Settings, get_settings

LOCAL_DATABASE_URL = 'postgresql+psycopg://postgres:postgres@localhost:5432/trippilot'

SETTINGS_ENV_NAMES = (
    'APP_ENV',
    'PUBLIC_BASE_URL',
    'DATABASE_URL',
    'DEMO_MODE',
    'ADMIN_EMAILS',
    'PAYPAL_MODE',
    'PAYPAL_API_BASE',
    'PAYPAL_WEB_BASE',
    'PAYPAL_CLIENT_ID',
    'PAYPAL_CLIENT_SECRET',
    'PAYPAL_WEBHOOK_ID',
    'PAYPAL_LOGIN_REDIRECT_URI',
    'VAULT_KEYS',
    'INVITE_SECRET',
    'DUFFEL_ACCESS_TOKEN',
    'APP_GIT_SHA',
)

REQUIRED_SECRET_FIELDS = ('invite_secret', 'vault_keys', 'paypal_client_id', 'paypal_client_secret')

SENTINEL_SECRET = 'sentinel-secret-value-123'  # noqa: S105 - fake value used to prove no leakage


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Remove every Settings variable from the environment and reset the settings cache."""
    for name in SETTINGS_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def build_settings(**overrides: Any) -> Settings:
    """Construct Settings without reading a local .env file."""
    return Settings(_env_file=None, **overrides)


def production_kwargs(**overrides: Any) -> dict[str, Any]:
    """Return a complete, valid set of staging/production values with optional overrides."""
    values: dict[str, Any] = {
        'app_env': 'production',
        'invite_secret': SENTINEL_SECRET,
        'vault_keys': SENTINEL_SECRET,
        'paypal_client_id': 'client-id-value',
        'paypal_client_secret': SENTINEL_SECRET,
        'database_url': 'postgresql://u:p@db.example.com:5432/trippilot',
    }
    values.update(overrides)
    return values


def test_defaults_are_local_dev_values() -> None:
    """With no environment, Settings gives the local fake-PayPal development defaults."""
    settings = build_settings()

    assert settings.app_env == 'local'
    assert settings.paypal_mode == 'fake'
    assert settings.demo_mode is False
    assert settings.database_url == LOCAL_DATABASE_URL
    assert settings.admin_emails == []
    assert settings.app_git_sha == 'dev'


@pytest.mark.parametrize(
    'raw_url',
    [
        'postgres://u:p@h:5432/db',
        'postgresql://u:p@h:5432/db',
        'postgresql+psycopg://u:p@h:5432/db',
    ],
)
def test_database_url_is_normalised_to_psycopg_driver(raw_url: str) -> None:
    """Every Postgres URL spelling ends up on the psycopg 3 driver."""
    settings = build_settings(database_url=raw_url)

    assert settings.database_url == 'postgresql+psycopg://u:p@h:5432/db'


def test_database_url_is_normalised_when_read_from_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The normalisation also applies to the DATABASE_URL environment variable."""
    monkeypatch.setenv('DATABASE_URL', 'postgres://u:p@h:5432/db')

    assert build_settings().database_url == 'postgresql+psycopg://u:p@h:5432/db'


def test_admin_emails_are_split_trimmed_and_lowercased(monkeypatch: pytest.MonkeyPatch) -> None:
    """ADMIN_EMAILS is a comma string that becomes a clean lowercase list."""
    monkeypatch.setenv('ADMIN_EMAILS', 'A@x.com, b@y.com')

    assert build_settings().admin_emails == ['a@x.com', 'b@y.com']


@pytest.mark.parametrize('missing_field', REQUIRED_SECRET_FIELDS)
@pytest.mark.parametrize('app_env', ['staging', 'production'])
def test_non_local_environments_refuse_to_start_without_required_secret(
    app_env: str, missing_field: str
) -> None:
    """Staging and production fail fast, naming the empty required field."""
    with pytest.raises(ValidationError) as excinfo:
        build_settings(**production_kwargs(app_env=app_env, **{missing_field: ''}))

    message = str(excinfo.value)
    assert missing_field in message
    assert SENTINEL_SECRET not in message


@pytest.mark.parametrize('app_env', ['staging', 'production'])
def test_non_local_environments_refuse_the_local_default_database_url(app_env: str) -> None:
    """Leaving DATABASE_URL at the local default outside local/test is a startup error."""
    with pytest.raises(ValidationError) as excinfo:
        build_settings(**production_kwargs(app_env=app_env, database_url=LOCAL_DATABASE_URL))

    assert 'database_url' in str(excinfo.value)


def test_non_local_environment_lists_every_empty_field_at_once() -> None:
    """One error reports all missing secrets rather than one per restart."""
    with pytest.raises(ValidationError) as excinfo:
        build_settings(app_env='staging')

    message = str(excinfo.value)
    for field in (*REQUIRED_SECRET_FIELDS, 'database_url'):
        assert field in message


def test_production_with_every_secret_and_a_real_database_constructs() -> None:
    """A fully configured production environment starts."""
    settings = build_settings(**production_kwargs())

    assert settings.app_env == 'production'
    assert settings.database_url == 'postgresql+psycopg://u:p@db.example.com:5432/trippilot'
    assert settings.invite_secret.get_secret_value() == SENTINEL_SECRET


def test_test_environment_allows_empty_secrets() -> None:
    """The test environment does not enforce production secrets."""
    settings = build_settings(app_env='test')

    assert settings.app_env == 'test'
    assert settings.invite_secret.get_secret_value() == ''


def test_secret_values_are_masked_in_repr() -> None:
    """SecretStr fields never show their value when Settings is printed."""
    settings = build_settings(**production_kwargs())

    assert SENTINEL_SECRET not in repr(settings)
    assert "invite_secret=SecretStr('**********')" in repr(settings)


def test_get_settings_is_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    """get_settings returns the same instance until the cache is cleared."""
    monkeypatch.setenv('APP_ENV', 'test')

    first = get_settings()
    monkeypatch.setenv('APP_ENV', 'local')

    assert first.app_env == 'test'
    assert get_settings() is first


@pytest.fixture
def configured_logging() -> Iterator[None]:
    """Configure structlog for a test and restore the defaults afterwards."""
    configure_logging()
    yield
    structlog.reset_defaults()
    logging.getLogger('uvicorn.access').disabled = False


def test_log_redaction_masks_sensitive_keys(
    configured_logging: None, capsys: pytest.CaptureFixture[str]
) -> None:
    """Values under sensitive keys, including nested ones, render as a mask."""
    structlog.get_logger().info(
        'checkout',
        token='tok-raw-value',  # noqa: S106 - fake value used to prove masking
        state='state-raw-value',
        invite='invite-raw-value',
        nested={'Authorization': 'Bearer raw-bearer-value', 'safe': 'visible-value'},
        trip_id='trip-123',
    )

    output = capsys.readouterr().out
    for raw in ('tok-raw-value', 'state-raw-value', 'invite-raw-value', 'raw-bearer-value'):
        assert raw not in output
    event = json.loads(output.strip().splitlines()[-1])
    assert event['token'] == '***'  # noqa: S105
    assert event['state'] == '***'
    assert event['invite'] == '***'
    assert event['nested']['Authorization'] == '***'
    assert event['nested']['safe'] == 'visible-value'
    assert event['trip_id'] == 'trip-123'


@pytest.mark.parametrize(
    'key',
    ['secret', 'authorization', 'payment_token', 'vault_id', 'code', 'password', 'cookie'],
)
def test_log_redaction_masks_every_listed_key(
    configured_logging: None, capsys: pytest.CaptureFixture[str], key: str
) -> None:
    """Each key named in the redaction list is masked, in any letter case."""
    structlog.get_logger().info('event', **{key.upper(): 'raw-value-to-hide'})

    output = capsys.readouterr().out
    assert 'raw-value-to-hide' not in output


def test_uvicorn_access_logger_is_disabled(configured_logging: None) -> None:
    """The uvicorn access log is off because its URLs carry invite and OAuth values."""
    assert logging.getLogger('uvicorn.access').disabled is True

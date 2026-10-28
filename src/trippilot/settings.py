"""Typed application settings for every Phase 1 environment variable.

`Settings` is the single source of configuration. Non-secret fields default to local
development values, secrets default to empty, and staging or production refuse to start
when a required secret is empty (fail fast, never print secret values).
"""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated, Any, Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

LOCAL_DATABASE_URL = 'postgresql+psycopg://postgres:postgres@localhost:5432/trippilot'
"""The local development database URL; staging and production must override it."""

_DRIVER_PREFIXES = ('postgres://', 'postgresql://')
_DRIVER_SCHEME = 'postgresql+psycopg://'


class Settings(BaseSettings):
    """Application configuration read from the environment and an optional `.env` file."""

    model_config = SettingsConfigDict(env_file='.env', extra='ignore')

    app_env: Literal['local', 'test', 'staging', 'production'] = 'local'
    public_base_url: str = 'http://localhost:8000'
    database_url: str = LOCAL_DATABASE_URL
    demo_mode: bool = False
    admin_emails: Annotated[list[str], NoDecode] = Field(default_factory=list)

    paypal_mode: Literal['fake', 'sandbox'] = 'fake'
    paypal_api_base: str = 'https://api-m.sandbox.paypal.com'
    paypal_web_base: str = 'https://www.sandbox.paypal.com'
    paypal_client_id: str = ''
    paypal_client_secret: SecretStr = SecretStr('')
    paypal_webhook_id: str = ''
    paypal_login_redirect_uri: str = ''

    vault_keys: SecretStr = SecretStr('')
    invite_secret: SecretStr = SecretStr('')
    duffel_access_token: SecretStr = SecretStr('')
    app_git_sha: str = 'dev'

    @field_validator('database_url')
    @classmethod
    def _normalise_database_url(cls, value: str) -> str:
        """Point `postgres://` and `postgresql://` URLs at the psycopg 3 driver."""
        for prefix in _DRIVER_PREFIXES:
            if value.startswith(prefix):
                return _DRIVER_SCHEME + value[len(prefix) :]
        return value

    @field_validator('admin_emails', mode='before')
    @classmethod
    def _parse_admin_emails(cls, value: Any) -> Any:
        """Accept a comma-separated string and return a trimmed, lowercased list."""
        if isinstance(value, str):
            return [part.strip().lower() for part in value.split(',') if part.strip()]
        if isinstance(value, list):
            return [str(part).strip().lower() for part in value if str(part).strip()]
        return value

    @model_validator(mode='after')
    def _require_secrets_outside_local(self) -> Settings:
        """Refuse to start staging or production with empty secrets or the local database."""
        if self.app_env not in ('staging', 'production'):
            return self
        missing: list[str] = []
        if not self.invite_secret.get_secret_value():
            missing.append('invite_secret')
        if not self.vault_keys.get_secret_value():
            missing.append('vault_keys')
        if not self.paypal_client_id:
            missing.append('paypal_client_id')
        if not self.paypal_client_secret.get_secret_value():
            missing.append('paypal_client_secret')
        if self.database_url == LOCAL_DATABASE_URL:
            missing.append('database_url')
        if missing:
            names = ', '.join(missing)
            raise ValueError(f'{self.app_env} requires non-empty settings: {names}')
        return self


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings instance, built once and cached."""
    return Settings()

"""Typed application settings (stub for the RED commit)."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Placeholder with no fields so the behaviour tests fail on their assertions."""

    model_config = SettingsConfigDict(extra='ignore')


@lru_cache
def get_settings() -> Settings:
    """Return the cached settings instance."""
    return Settings()

"""Async SQLAlchemy engine, session factory and the `get_db` request dependency.

The engine is built lazily from `get_settings()` so importing this module never opens a
connection and tests can point the settings at a throwaway database first.
"""

from __future__ import annotations

import asyncio
import sys
from collections.abc import AsyncIterator
from functools import lru_cache

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from trippilot.settings import get_settings


def configure_event_loop_policy() -> None:
    """Select the Selector event loop on Windows; a no-op elsewhere.

    psycopg async is not compatible with the default Windows ProactorEventLoop (RESEARCH R5),
    so the policy must be set before any event loop is created.
    """
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(expire_on_commit=False)
"""Session factory; `get_engine()` binds it to the engine the first time one is created."""


@lru_cache
def get_engine() -> AsyncEngine:
    """Return the process-wide async engine, created on first use, and bind the factory to it."""
    engine = create_async_engine(get_settings().database_url, pool_size=5, max_overflow=5)
    session_factory.configure(bind=engine)
    return engine


async def dispose_engine() -> None:
    """Dispose the cached engine and forget it, so the next use rebuilds it from settings."""
    if get_engine.cache_info().currsize:
        await get_engine().dispose()
        get_engine.cache_clear()


async def get_db() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency yielding a session that commits on success and rolls back on error."""
    get_engine()
    async with session_factory() as session:
        try:
            yield session
            await session.commit()
        except BaseException:
            await session.rollback()
            raise

"""Opaque, DB-backed session tokens and the `tp_session` cookie (D-03).

The cookie carries a 256-bit random token. Only `sha256(token)` (32 bytes) is stored, so a
database read never yields a usable cookie (threat T-01-01). Sliding renewal arrives with 01-12.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import Response
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from trippilot.auth.models import SessionRow
from trippilot.settings import Settings

SESSION_COOKIE_NAME = 'tp_session'
SESSION_TTL = timedelta(days=30)
_LOCAL_ENVIRONMENTS = frozenset({'local', 'test'})


def hash_token(raw: str) -> bytes:
    """Return the 32-byte sha256 digest under which a raw cookie value is stored."""
    return hashlib.sha256(raw.encode()).digest()


async def create_session(
    db: AsyncSession, account_id: uuid.UUID, *, is_persona: bool, user_agent: str | None
) -> str:
    """Insert a session row for the account and return the raw cookie value.

    The caller owns the transaction: the row is flushed, not committed. The raw value exists
    only in the return value; nothing but its hash is persisted.
    """
    raw = secrets.token_urlsafe(32)
    db.add(
        SessionRow(
            id_hash=hash_token(raw),
            account_id=account_id,
            expires_at=datetime.now(UTC) + SESSION_TTL,
            user_agent=user_agent,
            is_persona=is_persona,
        )
    )
    await db.flush()
    return raw


async def load_session(db: AsyncSession, raw: str) -> SessionRow | None:
    """Return the live session for a raw cookie value, or None if unknown or expired."""
    result = await db.execute(
        select(SessionRow).where(
            SessionRow.id_hash == hash_token(raw), SessionRow.expires_at > datetime.now(UTC)
        )
    )
    return result.scalar_one_or_none()


async def delete_session(db: AsyncSession, raw: str) -> None:
    """Delete the session for a raw cookie value (a no-op if there is none)."""
    await db.execute(delete(SessionRow).where(SessionRow.id_hash == hash_token(raw)))


def set_session_cookie(response: Response, raw: str, settings: Settings) -> None:
    """Attach the session cookie: HttpOnly, SameSite=Lax, Secure outside local and test."""
    response.set_cookie(
        SESSION_COOKIE_NAME,
        raw,
        max_age=int(SESSION_TTL.total_seconds()),
        path='/',
        httponly=True,
        samesite='lax',
        secure=settings.app_env not in _LOCAL_ENVIRONMENTS,
    )


def clear_session_cookie(response: Response) -> None:
    """Send a clearing Set-Cookie (Max-Age=0) for the session cookie."""
    response.delete_cookie(SESSION_COOKIE_NAME, path='/', httponly=True, samesite='lax')

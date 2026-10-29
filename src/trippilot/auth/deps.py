"""Request dependencies: the signed-in account and session, required or optional."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from trippilot.auth.models import Account, SessionRow
from trippilot.auth.sessions import (
    SESSION_COOKIE_NAME,
    load_session,
    set_session_cookie,
    touch_session,
)
from trippilot.db.engine import get_db
from trippilot.settings import Settings

DbSession = Annotated[AsyncSession, Depends(get_db)]


def app_settings(request: Request) -> Settings:
    """Return the settings the running app was built with."""
    settings: Settings = request.app.state.settings
    return settings


AppSettings = Annotated[Settings, Depends(app_settings)]


async def optional_session(
    request: Request, response: Response, db: DbSession, settings: AppSettings
) -> SessionRow | None:
    """Return the live session for the request cookie, or None when absent, unknown or expired.

    A live session more than an hour past its last renewal slides to 30 days from now and the
    cookie is re-issued on this response (D-03, ACC-04).
    """
    raw = request.cookies.get(SESSION_COOKIE_NAME)
    if not raw:
        return None
    session = await load_session(db, raw)
    if session is not None and touch_session(session):
        set_session_cookie(response, raw, settings)
    return session


async def require_session(
    session: Annotated[SessionRow | None, Depends(optional_session)],
) -> SessionRow:
    """Return the live session or raise 401."""
    if session is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, 'Not signed in')
    return session


async def optional_account(
    session: Annotated[SessionRow | None, Depends(optional_session)], db: DbSession
) -> Account | None:
    """Return the signed-in account, or None when there is no live session."""
    if session is None:
        return None
    return await db.get(Account, session.account_id)


async def require_account(
    account: Annotated[Account | None, Depends(optional_account)],
) -> Account:
    """Return the signed-in account or raise 401."""
    if account is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, 'Not signed in')
    return account


CurrentSession = Annotated[SessionRow, Depends(require_session)]
CurrentAccount = Annotated[Account, Depends(require_account)]
OptionalAccount = Annotated[Account | None, Depends(optional_account)]

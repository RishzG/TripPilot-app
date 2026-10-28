"""GET /api/me and POST /api/auth/signout."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Request, Response, status
from pydantic import BaseModel

from trippilot.auth.deps import CurrentAccount, CurrentSession, DbSession
from trippilot.auth.models import Account
from trippilot.auth.sessions import SESSION_COOKIE_NAME, clear_session_cookie, delete_session

router = APIRouter(tags=['auth'])


class MeResponse(BaseModel):
    """The signed-in account as the SPA needs it. `kind` is 'member' or 'persona'."""

    id: uuid.UUID
    display_name: str
    nickname: str | None
    avatar_kind: str
    avatar_key: str | None
    kind: str
    is_persona: bool


def me_response(account: Account, *, is_persona: bool) -> MeResponse:
    """Build the /api/me body for an account and the session's persona flag."""
    return MeResponse(
        id=account.id,
        display_name=account.display_name,
        nickname=account.nickname,
        avatar_kind=account.avatar_kind,
        avatar_key=account.avatar_key,
        kind=account.kind,
        is_persona=is_persona,
    )


@router.get('/api/me')
async def me(account: CurrentAccount, session: CurrentSession) -> MeResponse:
    """Return the account behind the session cookie (401 when there is none)."""
    return me_response(account, is_persona=session.is_persona)


@router.post('/api/auth/signout', status_code=status.HTTP_204_NO_CONTENT)
async def signout(request: Request, db: DbSession) -> Response:
    """Delete this browser's session row and clear the cookie; idempotent without a session."""
    raw = request.cookies.get(SESSION_COOKIE_NAME)
    if raw:
        await delete_session(db, raw)
        await db.commit()
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    clear_session_cookie(response)
    return response

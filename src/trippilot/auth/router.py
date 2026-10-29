"""Auth routes: /api/me, sign-out, sign-out-everywhere and Log in with PayPal (start, callback)."""

from __future__ import annotations

import uuid
from typing import Annotated, Literal, Self

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from trippilot.auth.avatars import ILLUSTRATED_AVATAR_KEYS
from trippilot.auth.deps import AppSettings, CurrentAccount, CurrentSession, DbSession
from trippilot.auth.models import Account
from trippilot.auth.paypal_login import (
    CALLBACK_PATH,
    OAUTH_COOKIE_NAME,
    SIGNIN_CANCELLED_URL,
    STATE_TTL,
    LoginStateError,
    complete_login,
    start_login,
)
from trippilot.auth.sessions import (
    SESSION_COOKIE_NAME,
    clear_session_cookie,
    cookie_secure,
    create_session,
    delete_all_sessions,
    delete_session,
    set_session_cookie,
)
from trippilot.contracts.paypal import PayPalGateway
from trippilot.payments import get_paypal_gateway
from trippilot.settings import Settings

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


NICKNAME_MAX_LENGTH = 40
AvatarKind = Literal['initials', 'illustrated']
"""The two ways an account can look (the `accounts.avatar_kind` check constraint)."""


class ProfileUpdate(BaseModel):
    """Body of PATCH /api/me: a new nickname and/or a new avatar (D-09, D-45).

    The nickname is trimmed and must be 1..40 characters. `avatar_kind` 'illustrated' needs a key
    from `ILLUSTRATED_AVATAR_KEYS`; 'initials' clears the key. A key without a kind, a body that
    changes nothing and any other field are refused with 422.
    """

    model_config = ConfigDict(extra='forbid')

    nickname: (
        Annotated[
            str,
            StringConstraints(strip_whitespace=True, min_length=1, max_length=NICKNAME_MAX_LENGTH),
        ]
        | None
    ) = None
    avatar_kind: AvatarKind | None = None
    avatar_key: str | None = Field(default=None, max_length=32)

    @model_validator(mode='after')
    def _check_combination(self) -> Self:
        """Refuse empty bodies, a key without a kind and an illustrated avatar outside the set."""
        if self.nickname is None and self.avatar_kind is None and self.avatar_key is None:
            raise ValueError('Nothing to change')
        if self.avatar_kind is None and self.avatar_key is not None:
            raise ValueError('avatar_key needs avatar_kind')
        if self.avatar_kind == 'illustrated' and self.avatar_key not in ILLUSTRATED_AVATAR_KEYS:
            raise ValueError('Unknown avatar')
        return self


@router.patch('/api/me')
async def update_me(
    body: ProfileUpdate, account: CurrentAccount, session: CurrentSession, db: DbSession
) -> MeResponse:
    """Change the signed-in member's nickname and/or avatar; nothing else is editable here.

    A demo persona is one shared account that every judge signs in as, so its profile is fixed
    (403); otherwise one visitor's nickname would show up in everyone else's demo.
    """
    if session.is_persona or account.kind == 'persona':
        raise HTTPException(status.HTTP_403_FORBIDDEN, 'Demo personas cannot change their profile')
    if body.nickname is not None:
        account.nickname = body.nickname
    if body.avatar_kind is not None:
        account.avatar_kind = body.avatar_kind
        account.avatar_key = body.avatar_key if body.avatar_kind == 'illustrated' else None
    await db.commit()
    return me_response(account, is_persona=False)


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


@router.post('/api/auth/signout-everywhere', status_code=status.HTTP_204_NO_CONTENT)
async def signout_everywhere(account: CurrentAccount, db: DbSession) -> Response:
    """End every session of the signed-in account (D-10) and clear this browser's cookie."""
    await delete_all_sessions(db, account.id)
    await db.commit()
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    clear_session_cookie(response)
    return response


OAUTH_COOKIE_PATH = '/api/auth'


def _set_oauth_cookie(response: Response, state: str, settings: Settings) -> None:
    """Bind the state to this browser: HttpOnly, SameSite=Lax, Secure outside local and test."""
    response.set_cookie(
        OAUTH_COOKIE_NAME,
        state,
        max_age=int(STATE_TTL.total_seconds()),
        path=OAUTH_COOKIE_PATH,
        httponly=True,
        samesite='lax',
        secure=cookie_secure(settings),
    )


def _clear_oauth_cookie(response: Response) -> None:
    """Send a clearing Set-Cookie for the state cookie."""
    response.delete_cookie(OAUTH_COOKIE_NAME, path=OAUTH_COOKIE_PATH, httponly=True, samesite='lax')


def _redirect(location: str) -> RedirectResponse:
    """Return a 302 that no cache may keep (the target depends on one-time state)."""
    response = RedirectResponse(location, status_code=status.HTTP_302_FOUND)
    response.headers['Cache-Control'] = 'no-store'
    return response


@router.get(
    '/api/auth/paypal/start',
    status_code=status.HTTP_302_FOUND,
    response_class=RedirectResponse,
    responses={302: {'description': 'Redirect to PayPal (or to /join-failed for a bad invite)'}},
)
async def paypal_start(
    db: DbSession,
    settings: AppSettings,
    invite: Annotated[str | None, Query(max_length=128)] = None,
    next_path: Annotated[str | None, Query(alias='next', max_length=2048)] = None,
) -> Response:
    """Begin Log in with PayPal: store a single-use state and redirect to PayPal's consent page."""
    started = await start_login(db, settings, invite, next_path)
    await db.commit()
    response = _redirect(started.redirect_url)
    if started.state is not None:
        _set_oauth_cookie(response, started.state, settings)
    return response


@router.get(
    CALLBACK_PATH,
    status_code=status.HTTP_302_FOUND,
    response_class=RedirectResponse,
    responses={302: {'description': 'Redirect into the app, signed in unless PayPal failed'}},
)
async def paypal_callback(
    request: Request,
    db: DbSession,
    settings: AppSettings,
    gateway: Annotated[PayPalGateway, Depends(get_paypal_gateway)],
    code: Annotated[str | None, Query(max_length=2048)] = None,
    state: Annotated[str | None, Query(max_length=256)] = None,
    error: Annotated[str | None, Query(max_length=256)] = None,
) -> Response:
    """Finish Log in with PayPal: check the state, open a brand-new session, redirect into the app.

    A state that is missing, reused, expired or not the cookie's answers 400 and issues no
    session. PayPal's own `error` (the person cancelled) goes back to the sign-in page.
    """
    if error is not None:
        response = _redirect(SIGNIN_CANCELLED_URL)
        _clear_oauth_cookie(response)
        return response
    if not code or not state:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, 'Sign-in could not be completed')
    try:
        outcome = await complete_login(
            db,
            gateway,
            settings,
            code=code,
            state=state,
            cookie_state=request.cookies.get(OAUTH_COOKIE_NAME),
        )
    except LoginStateError as refusal:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, 'This sign-in link expired or was already used'
        ) from refusal
    response = _redirect(outcome.redirect_to)
    if outcome.account_id is not None:
        previous = request.cookies.get(SESSION_COOKIE_NAME)
        if previous:
            await delete_session(db, previous)
        raw = await create_session(
            db,
            outcome.account_id,
            is_persona=False,
            user_agent=request.headers.get('user-agent'),
        )
        set_session_cookie(response, raw, settings)
    await db.commit()
    _clear_oauth_cookie(response)
    return response

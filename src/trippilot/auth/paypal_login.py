"""Log in with PayPal: the OIDC start and callback (ACC-02, D-04, D-21; RESEARCH Pattern 2).

`start_login` stores a hashed single-use `state` row (10 minutes) and returns the PayPal consent
URL; the raw state travels in the URL and in the `tp_oauth` cookie that binds it to this browser.
`complete_login` requires the two to match, atomically consumes the row, exchanges the code,
reads userinfo, upserts the account keyed on the PayPal subject claim (never the email,
Pitfall 11) and joins the invite the state carries.

The invite crosses the PayPal round trip as an `invite_id` only (D-21, T-01-36): the raw token is
neither stored nor placed in `state`, and is re-derived on return from the server secret.
Codes, states, tokens and claims are never logged.
"""

from __future__ import annotations

import hmac
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import NamedTuple
from urllib.parse import quote, urlencode

import structlog
from sqlalchemy import delete, func, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from trippilot.auth.models import Account, OAuthState
from trippilot.auth.sessions import hash_token
from trippilot.contracts.paypal import PayPalError, PayPalGateway
from trippilot.settings import Settings
from trippilot.trips.invites import InviteError, join_via_invite, raw_invite_token, resolve_invite

logger = structlog.get_logger(__name__)

OAUTH_COOKIE_NAME = 'tp_oauth'
STATE_TTL = timedelta(minutes=10)
STATE_PURGE_AFTER = timedelta(days=1)
LOGIN_SCOPE = 'openid profile email'
"""The scopes the 01-10 spike proved; the paypalattributes scope was rejected as invalid."""
USERINFO_SCHEMA = 'paypalv1.1'
CALLBACK_PATH = '/api/auth/paypal/callback'
MAX_NEXT_PATH_LENGTH = 2048
FALLBACK_NAME = 'Friend'
SIGNIN_FAILED_URL = '/signin?error=failed'
SIGNIN_CANCELLED_URL = '/signin?error=cancelled'


class LoginStateError(Exception):
    """The callback's state is missing, differs from the cookie, expired or was already used."""


class LoginStart(NamedTuple):
    """Where to send the browser, and the raw state for the `tp_oauth` cookie (None if no state)."""

    redirect_url: str
    state: str | None


@dataclass(frozen=True)
class LoginOutcome:
    """The result of a completed callback.

    `account_id` is None when sign-in failed at PayPal (no session is issued) and the redirect
    goes back to the sign-in page. Otherwise the caller opens a session for the account and
    redirects to `redirect_to`.
    """

    redirect_to: str
    account_id: uuid.UUID | None


def sanitize_next_path(next_path: str | None) -> str:
    """Return `next_path` when it is a same-origin relative path, else `/` (T-01-34).

    Accepts only a path that starts with a single `/`, has no backslash or control character
    and is not unreasonably long. Anything else (an absolute URL, `//host`, `/\\host`,
    `javascript:`) becomes the home page.
    """
    if not next_path or len(next_path) > MAX_NEXT_PATH_LENGTH:
        return '/'
    if not next_path.startswith('/') or next_path.startswith('//'):
        return '/'
    if '\\' in next_path or any(ord(char) < 0x20 or ord(char) == 0x7F for char in next_path):
        return '/'
    return next_path


def login_redirect_uri(settings: Settings) -> str:
    """Return the callback URL registered on the PayPal app (PAYPAL_LOGIN_REDIRECT_URI).

    When the setting is empty (local development) it is derived from the public base URL.
    """
    configured = settings.paypal_login_redirect_uri
    if configured:
        return configured
    return f'{settings.public_base_url.rstrip("/")}{CALLBACK_PATH}'


def authorize_url(settings: Settings, state: str) -> str:
    """Return the PayPal consent URL for a fresh state."""
    query = urlencode(
        {
            'flowEntry': 'static',
            'client_id': settings.paypal_client_id,
            'response_type': 'code',
            'scope': LOGIN_SCOPE,
            'redirect_uri': login_redirect_uri(settings),
            'state': state,
        },
        quote_via=quote,
    )
    return f'{settings.paypal_web_base.rstrip("/")}/connect?{query}'


async def start_login(
    db: AsyncSession, settings: Settings, invite_raw: str | None, next_path: str | None
) -> LoginStart:
    """Create the state row and return the PayPal consent URL and the raw state.

    An invite that does not resolve sends the visitor to the bad-link page instead (no state, no
    PayPal round trip). The caller commits.
    """
    invite_id: uuid.UUID | None = None
    if invite_raw:
        invite = await resolve_invite(db, invite_raw)
        if invite is None:
            return LoginStart('/join-failed?reason=not_found', None)
        invite_id = invite.id
    now = datetime.now(UTC)
    await db.execute(delete(OAuthState).where(OAuthState.expires_at < now - STATE_PURGE_AFTER))
    state = secrets.token_urlsafe(32)
    db.add(
        OAuthState(
            state_hash=hash_token(state),
            invite_id=invite_id,
            next_path=sanitize_next_path(next_path),
            expires_at=now + STATE_TTL,
        )
    )
    await db.flush()
    return LoginStart(authorize_url(settings, state), state)


async def _consume_state(
    db: AsyncSession, state: str, now: datetime
) -> tuple[uuid.UUID | None, str | None]:
    """Atomically mark an unused, unexpired state used; return its invite id and next path.

    The single UPDATE is the single-use guarantee: of two concurrent callbacks with the same
    state only one matches a row with `consumed_at IS NULL`.
    """
    result = await db.execute(
        update(OAuthState)
        .where(
            OAuthState.state_hash == hash_token(state),
            OAuthState.consumed_at.is_(None),
            OAuthState.expires_at > now,
        )
        .values(consumed_at=now)
        .returning(OAuthState.invite_id, OAuthState.next_path)
        .execution_options(synchronize_session=False)
    )
    row = result.one_or_none()
    if row is None:
        raise LoginStateError('state is unknown, expired or already used')
    invite_id: uuid.UUID | None = row[0]
    next_path: str | None = row[1]
    return invite_id, next_path


def _display_name(given_name: str | None, name: str | None) -> str:
    """Return the name to greet someone by: given name, else the first word of name (D-09)."""
    if given_name:
        return given_name
    if name and name.split():
        return name.split()[0]
    return FALLBACK_NAME


async def _upsert_account(
    db: AsyncSession, subject: str, email: str | None, display_name: str
) -> Account:
    """Insert the account for a PayPal subject or refresh its email; never keyed on email."""
    values = insert(Account).values(
        kind='member', paypal_subject=subject, email=email, display_name=display_name
    )
    statement = values.on_conflict_do_update(
        index_elements=[Account.paypal_subject],
        set_={'email': func.coalesce(values.excluded.email, Account.email)},
    ).returning(Account)
    result = await db.execute(statement, execution_options={'populate_existing': True})
    account: Account = result.scalar_one()
    return account


async def complete_login(
    db: AsyncSession,
    gateway: PayPalGateway,
    settings: Settings,
    *,
    code: str,
    state: str,
    cookie_state: str | None,
) -> LoginOutcome:
    """Finish a Log in with PayPal callback.

    Raises `LoginStateError` when `state` is not the cookie's state or its row is unknown,
    expired or used (the caller answers 400 and issues no session). A PayPal failure after the
    state is consumed returns an outcome with no account. An invite that cannot be joined
    (closed, full, removed per UD-4, or no longer valid) still signs the person in and redirects
    to `/join-failed?reason=...`. The caller commits and opens the session.
    """
    if (
        not state
        or not cookie_state
        or not hmac.compare_digest(state.encode(), cookie_state.encode())
    ):
        raise LoginStateError('state does not match the cookie')
    invite_id, next_path = await _consume_state(db, state, datetime.now(UTC))
    try:
        tokens = await gateway.exchange_login_code(
            code=code, redirect_uri=login_redirect_uri(settings)
        )
        info = await gateway.get_userinfo(access_token=tokens.access_token, schema=USERINFO_SCHEMA)
    except PayPalError as error:
        logger.warning('paypal_login_failed', **error.summary())
        return LoginOutcome(SIGNIN_FAILED_URL, None)
    subject = info.subject
    if subject is None:
        logger.warning('paypal_login_without_subject')
        return LoginOutcome(SIGNIN_FAILED_URL, None)

    account = await _upsert_account(
        db, subject, info.email, _display_name(info.given_name, info.name)
    )
    if invite_id is None:
        return LoginOutcome(sanitize_next_path(next_path), account.id)
    try:
        joined = await join_via_invite(db, raw_invite_token(settings, invite_id), account)
    except InviteError as refusal:
        return LoginOutcome(f'/join-failed?reason={refusal.reason}', account.id)
    return LoginOutcome(f'/welcome/{joined.trip_id}', account.id)

"""HTTP routes under /api/paypal: public config and a member's saved PayPal (ACC-03).

Plan 01-21 created this seam, 01-08 adds the vault routes, 01-13 includes the webhook router and
01-14 adds the pool routes. Every vault route needs a signed-in account and every pool route needs a
team admin (D-37). No response carries a payment token id, a customer id or anyone else's
saved-PayPal status (D-08).
"""

from __future__ import annotations

import logging
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from trippilot.admin.deps import AdminAccount
from trippilot.auth.deps import AppSettings, CurrentAccount, CurrentSession, DbSession
from trippilot.contracts.paypal import PayPalError, PayPalGateway
from trippilot.payments import get_paypal_gateway
from trippilot.payments.ledger import Actor
from trippilot.payments.models import PoolBuyer
from trippilot.payments.pool import (
    POOL_OWNER_KIND,
    PoolError,
    active_vault_token_id,
    add_pool_buyer,
    get_pool_buyer,
    list_pool,
    mark_enrolled,
)
from trippilot.payments.vault_flow import (
    VaultFlowError,
    complete_setup,
    remove_saved,
    start_setup,
)
from trippilot.payments.vault_store import VaultError, VaultStore, parse_vault_keys
from trippilot.payments.webhooks import router as webhooks_router

log = logging.getLogger(__name__)

router = APIRouter(prefix='/api/paypal', tags=['paypal'])
router.include_router(webhooks_router)  # POST /api/paypal/webhooks (01-13)

OWNER_KIND = 'account'
"""Members save PayPal against their account; pool buyers use 'pool_buyer' (01-14)."""


class PayPalConfig(BaseModel):
    """The browser-safe PayPal settings the v6 SDK needs."""

    model_config = ConfigDict(populate_by_name=True)

    client_id: str = Field(serialization_alias='clientId')
    environment: Literal['sandbox']


class VaultSetupTokenResponse(BaseModel):
    """The setup token the SDK's `createVaultToken` resolves with."""

    model_config = ConfigDict(populate_by_name=True)

    vault_setup_token: str = Field(serialization_alias='vaultSetupToken')


class VaultPaymentTokenRequest(BaseModel):
    """Body of POST /vault/payment-token: the setup token the buyer just approved."""

    model_config = ConfigDict(populate_by_name=True)

    vault_setup_token: str = Field(alias='vaultSetupToken', min_length=1, max_length=200)


class VaultStatus(BaseModel):
    """Whether the caller has a saved PayPal. Nothing else about it is ever returned."""

    saved: bool


def get_vault_store(settings: AppSettings) -> VaultStore:
    """Build the store from `VAULT_KEYS`; answer 503 when no valid key is configured."""
    try:
        return VaultStore(parse_vault_keys(settings.vault_keys.get_secret_value()))
    except VaultError as error:
        log.error('vault is not usable: %s', error)
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, 'vault_unavailable') from error


Gateway = Annotated[PayPalGateway, Depends(get_paypal_gateway)]
Store = Annotated[VaultStore, Depends(get_vault_store)]


def _actor(account_id: UUID, *, is_persona: bool) -> Actor:
    """Return the ledger actor for the signed-in session: a persona or a member."""
    return Actor(kind='persona' if is_persona else 'member', id=str(account_id))


def _paypal_unavailable(error: PayPalError) -> HTTPException:
    """Log PayPal's safe error fields and return a 502 that carries none of them."""
    log.warning('PayPal refused a vault call: %s', error.summary())
    return HTTPException(status.HTTP_502_BAD_GATEWAY, 'paypal_unavailable')


@router.get('/config')
async def paypal_config(settings: AppSettings) -> PayPalConfig:
    """Return the public client id and environment; nothing secret."""
    return PayPalConfig(client_id=settings.paypal_client_id, environment='sandbox')


@router.post('/vault/setup-token')
async def create_vault_setup_token(
    account: CurrentAccount,
    db: DbSession,
    gateway: Gateway,
    settings: AppSettings,
    _store: Store,
) -> VaultSetupTokenResponse:
    """Start the save-PayPal flow: issue a setup token bound to the caller (30 minutes)."""
    try:
        setup_token = await start_setup(db, gateway, OWNER_KIND, account.id, settings)
    except PayPalError as error:
        raise _paypal_unavailable(error) from error
    await db.commit()
    return VaultSetupTokenResponse(vault_setup_token=setup_token)


@router.post('/vault/payment-token')
async def create_vault_payment_token(
    body: VaultPaymentTokenRequest,
    account: CurrentAccount,
    session: CurrentSession,
    db: DbSession,
    gateway: Gateway,
    store: Store,
) -> VaultStatus:
    """Finish the save: exchange the approved setup token and store the payment token."""
    actor = _actor(account.id, is_persona=session.is_persona)
    try:
        await complete_setup(
            db, gateway, store, OWNER_KIND, account.id, body.vault_setup_token, actor
        )
    except VaultFlowError as error:
        raise HTTPException(error.status_code, error.code) from error
    except PayPalError as error:
        raise _paypal_unavailable(error) from error
    await db.commit()
    return VaultStatus(saved=True)


@router.get('/vault/status')
async def vault_status(account: CurrentAccount, db: DbSession, store: Store) -> VaultStatus:
    """Return whether the caller has a saved PayPal (never anyone else's)."""
    return VaultStatus(saved=await store.status(db, OWNER_KIND, account.id))


@router.delete('/vault')
async def remove_vault(
    account: CurrentAccount,
    session: CurrentSession,
    db: DbSession,
    gateway: Gateway,
    store: Store,
) -> VaultStatus:
    """Remove the caller's saved PayPal at PayPal and in TripPilot; idempotent."""
    actor = _actor(account.id, is_persona=session.is_persona)
    try:
        await remove_saved(db, gateway, store, OWNER_KIND, account.id, actor)
    except PayPalError as error:
        await db.rollback()  # keep the saved token: PayPal still has it
        raise _paypal_unavailable(error) from error
    await db.commit()
    return VaultStatus(saved=False)


# -- pool buyers (plan 01-14): team admins enrol the simulated friends' saved PayPal -------------

SLUG_PATTERN = r'^[a-z][a-z0-9-]{0,31}$'
EMAIL_PATTERN = r'^[^@\s]{1,100}@[^@\s]{1,100}$'


class AddPoolBuyerRequest(BaseModel):
    """Body of POST /pool/buyers: the buyer's slug, the persona it backs and its sandbox email."""

    slug: str = Field(pattern=SLUG_PATTERN)
    persona_slug: str | None = Field(default=None, pattern=SLUG_PATTERN)
    sandbox_email: str | None = Field(default=None, max_length=254, pattern=EMAIL_PATTERN)


class PoolBuyerOut(BaseModel):
    """One pool buyer as the enrolment page sees it. Never carries a token id of any kind."""

    slug: str
    persona_slug: str | None
    sandbox_email: str | None
    status: Literal['pending', 'enrolled', 'retired']


def _pool_out(buyer: PoolBuyer) -> PoolBuyerOut:
    """Allow-list a buyer row into its response."""
    return PoolBuyerOut.model_validate(
        {
            'slug': buyer.slug,
            'persona_slug': buyer.persona_slug,
            'sandbox_email': buyer.sandbox_email,
            'status': buyer.status,
        }
    )


async def _enrollable_buyer(db: DbSession, settings: AppSettings, slug: str) -> PoolBuyer:
    """Return this environment's buyer for `slug`, or raise 404 (unknown) or 409 (retired)."""
    buyer = await get_pool_buyer(db, slug, settings.app_env)
    if buyer is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, 'not_found')
    if buyer.status == 'retired':
        raise HTTPException(status.HTTP_409_CONFLICT, 'retired')
    return buyer


@router.get('/pool/buyers')
async def list_pool_buyers(
    _admin: AdminAccount, db: DbSession, settings: AppSettings
) -> list[PoolBuyerOut]:
    """List this environment's pool buyers: slug, persona, sandbox email and status only."""
    return [_pool_out(buyer) for buyer in await list_pool(db, settings.app_env)]


@router.post('/pool/buyers', status_code=status.HTTP_201_CREATED)
async def create_pool_buyer(
    body: AddPoolBuyerRequest, _admin: AdminAccount, db: DbSession, settings: AppSettings
) -> PoolBuyerOut:
    """Add a pending pool buyer to this environment; 409 when the slug already exists."""
    try:
        buyer = await add_pool_buyer(
            db, body.slug, body.persona_slug, body.sandbox_email, settings.app_env
        )
    except PoolError as error:
        raise HTTPException(error.status_code, error.code) from error
    await db.commit()
    return _pool_out(buyer)


@router.post('/pool/{slug}/setup-token')
async def create_pool_setup_token(
    slug: str,
    _admin: AdminAccount,
    db: DbSession,
    gateway: Gateway,
    settings: AppSettings,
    _store: Store,
) -> VaultSetupTokenResponse:
    """Start saving PayPal for a pool buyer: a setup token bound to that buyer (30 minutes)."""
    buyer = await _enrollable_buyer(db, settings, slug)
    try:
        setup_token = await start_setup(db, gateway, POOL_OWNER_KIND, buyer.id, settings)
    except PayPalError as error:
        raise _paypal_unavailable(error) from error
    await db.commit()
    return VaultSetupTokenResponse(vault_setup_token=setup_token)


@router.post('/pool/{slug}/payment-token')
async def create_pool_payment_token(
    slug: str,
    body: VaultPaymentTokenRequest,
    admin: AdminAccount,
    db: DbSession,
    gateway: Gateway,
    settings: AppSettings,
    store: Store,
) -> PoolBuyerOut:
    """Finish enrolling a pool buyer: store its approved token and mark the buyer enrolled.

    Re-enrolling replaces the earlier token (one active row). The setup token must have been
    issued for this same buyer; one issued for another buyer or for an account is 403.
    """
    buyer = await _enrollable_buyer(db, settings, slug)
    try:
        await complete_setup(
            db,
            gateway,
            store,
            POOL_OWNER_KIND,
            buyer.id,
            body.vault_setup_token,
            Actor(kind='member', id=str(admin.id)),
        )
        token_id = await active_vault_token_id(db, buyer.id)
        if token_id is None:  # complete_setup just saved one; this is a defensive guard
            raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, 'not_saved')
        await mark_enrolled(db, slug, token_id)
    except VaultFlowError as error:
        raise HTTPException(error.status_code, error.code) from error
    except PoolError as error:
        raise HTTPException(error.status_code, error.code) from error
    except PayPalError as error:
        raise _paypal_unavailable(error) from error
    await db.commit()
    await db.refresh(buyer)
    return _pool_out(buyer)

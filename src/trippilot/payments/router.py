"""HTTP routes under /api/paypal: public config and a member's saved PayPal (ACC-03).

Plan 01-21 created this seam, 01-08 adds the vault routes, 01-13 includes the webhook router and
01-14 adds the pool routes. Every vault route needs a signed-in account. No response carries a
payment token id, a customer id or anyone else's saved-PayPal status (D-08).
"""

from __future__ import annotations

import logging
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from trippilot.auth.deps import AppSettings, CurrentAccount, CurrentSession, DbSession
from trippilot.contracts.paypal import PayPalError, PayPalGateway
from trippilot.payments import get_paypal_gateway
from trippilot.payments.ledger import Actor
from trippilot.payments.vault_flow import (
    VaultFlowError,
    complete_setup,
    remove_saved,
    start_setup,
)
from trippilot.payments.vault_store import VaultError, VaultStore, parse_vault_keys

log = logging.getLogger(__name__)

router = APIRouter(prefix='/api/paypal', tags=['paypal'])

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

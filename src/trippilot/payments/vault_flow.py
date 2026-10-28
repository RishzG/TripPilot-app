"""Save, check and remove a member's saved PayPal (ACC-03; D-01, D-05, D-07, D-08).

The flow is the only caller of the PayPal vault gateway methods for members. Nothing here returns
or logs a payment token id or customer id: callers get booleans and our own row ids at most.
Money is never moved; saving a PayPal charges and holds nothing.
"""

from __future__ import annotations

import logging
import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from trippilot.contracts.paypal import PayPalError, PayPalGateway
from trippilot.payments.ledger import Actor, append_ledger_entry
from trippilot.payments.models import PendingVaultSetup
from trippilot.payments.vault_store import VaultStore
from trippilot.settings import Settings

log = logging.getLogger(__name__)

SETUP_TTL = timedelta(minutes=30)
"""How long a setup token may be completed after it is issued (T-01-23)."""

PURGE_AFTER = timedelta(days=1)
"""Expired pending rows older than this are deleted when a new setup starts."""


class VaultFlowError(Exception):
    """A refusal the router turns into an HTTP status (404 `not_found`, 403 `forbidden`)."""

    def __init__(self, status_code: int, code: str) -> None:
        """Record the HTTP status and the short machine code."""
        self.status_code = status_code
        self.code = code
        super().__init__(code)


async def start_setup(
    db: AsyncSession,
    gateway: PayPalGateway,
    owner_kind: str,
    owner_id: UUID,
    settings: Settings,
) -> str:
    """Issue a PayPal setup token for the owner and remember who it belongs to.

    Each click is a new setup, so the request id is fresh. `return_url` and `cancel_url` point at
    SPA routes for the redirect fallback of the v6 popup (RESEARCH Pitfall 3). The caller commits.

    Returns:
        The setup token id, which the browser hands to the PayPal SDK (it is not a payment token).
    """
    now = datetime.now(UTC)
    base = settings.public_base_url.rstrip('/')
    token = await gateway.create_setup_token(
        request_id=f'vault-setup-{owner_id}-{secrets.token_hex(8)}',
        return_url=f'{base}/vault/return',
        cancel_url=f'{base}/vault/cancel',
    )
    await db.execute(
        delete(PendingVaultSetup).where(PendingVaultSetup.expires_at < now - PURGE_AFTER)
    )
    db.add(
        PendingVaultSetup(
            setup_token_id=token.id,
            owner_kind=owner_kind,
            owner_id=owner_id,
            expires_at=now + SETUP_TTL,
        )
    )
    await db.flush()
    return token.id


async def complete_setup(
    db: AsyncSession,
    gateway: PayPalGateway,
    store: VaultStore,
    owner_kind: str,
    owner_id: UUID,
    setup_token_id: str,
    actor: Actor,
) -> None:
    """Turn an approved setup token into a stored payment token for the owner who started it.

    The payment-token call uses the deterministic request id `vault-pt-{setup_token_id}`, so a
    replay (double tap, retry after a timeout) gets the same PayPal token back and stores nothing
    new. Saving supersedes any earlier token for the owner, which is then deleted at PayPal.
    The caller commits.

    Raises:
        VaultFlowError: 404 when the setup token is unknown or expired, 403 when it belongs to
            another owner.
        PayPalError: when PayPal refuses the exchange.
    """
    result = await db.execute(
        select(PendingVaultSetup, PendingVaultSetup.expires_at > datetime.now(UTC)).where(
            PendingVaultSetup.setup_token_id == setup_token_id
        )
    )
    found = result.first()
    if found is None or not found[1]:
        raise VaultFlowError(404, 'not_found')
    pending = found[0]
    if pending.owner_kind != owner_kind or pending.owner_id != owner_id:
        raise VaultFlowError(403, 'forbidden')

    token = await gateway.create_payment_token(
        request_id=f'vault-pt-{setup_token_id}', setup_token_id=setup_token_id
    )
    saved = await store.save(db, owner_kind, owner_id, token, actor)
    superseded = saved.superseded_payment_token_id
    if superseded is not None and superseded != token.id:
        await _delete_superseded(db, gateway, superseded, actor)


async def _delete_superseded(
    db: AsyncSession, gateway: PayPalGateway, payment_token_id: str, actor: Actor
) -> None:
    """Delete the replaced token at PayPal; a failure is logged and ledgered, never fatal.

    The new token is already saved, so failing the whole request would leave the member with a
    working token and an error. A PayPal 404 means it is already gone.
    """
    try:
        await gateway.delete_payment_token(payment_token_id=payment_token_id)
    except PayPalError as error:
        if error.status == 404:
            return
        log.warning('could not delete a superseded vault token: %s', error.summary())
        await append_ledger_entry(
            db,
            action='vault.superseded_delete_failed',
            actor_kind=actor.kind,
            actor_id=actor.id,
            detail={'paypal_error': error.summary()},
        )


async def remove_saved(
    db: AsyncSession,
    gateway: PayPalGateway,
    store: VaultStore,
    owner_kind: str,
    owner_id: UUID,
    actor: Actor,
) -> bool:
    """Delete the owner's token at PayPal and soft-delete our row (D-07).

    Returns:
        True when a saved token was removed, False when nothing was saved. If PayPal refuses the
        delete the `PayPalError` propagates, the caller does not commit, and the row stays so the
        member can retry. (The open-hold block of D-07 arrives with holds in Phase 3.)
    """
    payment_token_id = await store.remove(db, owner_kind, owner_id, actor)
    if payment_token_id is None:
        return False
    try:
        await gateway.delete_payment_token(payment_token_id=payment_token_id)
    except PayPalError as error:
        if error.status != 404:
            raise
    return True

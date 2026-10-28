"""Encrypted vault token storage (stub; implemented in the GREEN commit of plan 01-08)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from trippilot.contracts.paypal import PaymentToken
from trippilot.payments.ledger import Actor, ActorKind


class VaultError(Exception):
    """A vault operation could not be done."""


@dataclass(frozen=True)
class SaveResult:
    """The outcome of saving a token."""

    vault_token_id: UUID
    superseded_payment_token_id: str | None


class VaultStore:
    """Encrypts payment tokens at rest."""

    key_version: int = 0

    def __init__(self, keys: Sequence[str]) -> None:
        """Build the store from keys, newest first."""

    async def save(
        self, db: AsyncSession, owner_kind: str, owner_id: UUID, token: PaymentToken, actor: Actor
    ) -> SaveResult:
        """Store a token for an owner."""
        raise NotImplementedError

    async def use_token(
        self,
        db: AsyncSession,
        vault_token_id: UUID,
        *,
        actor_kind: ActorKind,
        actor_id: str | None,
        purpose: str,
        request_id: str,
        trip_id: UUID | None = None,
    ) -> str:
        """Decrypt a token for use and ledger the use."""
        raise NotImplementedError

    async def remove(
        self, db: AsyncSession, owner_kind: str, owner_id: UUID, actor: Actor
    ) -> str | None:
        """Soft-delete the owner's active token."""
        raise NotImplementedError

    async def status(self, db: AsyncSession, owner_kind: str, owner_id: UUID) -> bool:
        """True when the owner has an active token."""
        raise NotImplementedError

    async def rotate(self, db: AsyncSession) -> int:
        """Re-encrypt rows under the newest key."""
        raise NotImplementedError

"""Encrypted storage for saved PayPal tokens (D-05, T-01-22).

This is the only module that imports `cryptography` and the only reader of
`vault_tokens.token_ciphertext`; the import-linter contracts and
`tests/unit/test_import_boundaries.py` enforce both. The ciphertext is a Fernet token of a JSON
object holding the payment token id and the customer id, so neither appears in any plain column,
response or log line. The keys come from the `VAULT_KEYS` environment variable (comma separated,
newest first) and never touch the database.

Every use of a token writes a `ledger_entries` row in the caller's transaction (see `use_token`),
and so do saving and removing one.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from trippilot.contracts.paypal import PaymentToken
from trippilot.payments.ledger import Actor, ActorKind, append_ledger_entry
from trippilot.payments.models import VaultToken


class VaultError(Exception):
    """A vault operation could not be done. The message never carries a token or a key."""


@dataclass(frozen=True)
class SaveResult:
    """The outcome of saving a token: our row id and the token it replaced, if any."""

    vault_token_id: UUID
    superseded_payment_token_id: str | None


def parse_vault_keys(raw: str) -> list[str]:
    """Split the comma-separated `VAULT_KEYS` value into keys, newest first."""
    return [part.strip() for part in raw.split(',') if part.strip()]


def key_fingerprint(key: str) -> int:
    """Return a stable non-secret number naming a key (31 bits of its SHA-256).

    Stored as `vault_tokens.key_version` so a rotation can find rows not yet under the newest key.
    """
    return int.from_bytes(hashlib.sha256(key.encode()).digest()[:4], 'big') & 0x7FFFFFFF


class VaultStore:
    """Encrypts payment tokens at rest with `MultiFernet` and records every use in the ledger."""

    def __init__(self, keys: Sequence[str]) -> None:
        """Build the store from Fernet keys, newest first.

        Raises:
            VaultError: when no key is given or a key is not a valid Fernet key.
        """
        cleaned = [key.strip() for key in keys if key.strip()]
        if not cleaned:
            raise VaultError('no vault key is configured')
        try:
            self._fernet = MultiFernet([Fernet(key) for key in cleaned])
        except ValueError as error:
            raise VaultError('a vault key is not a valid Fernet key') from error
        self._key_version = key_fingerprint(cleaned[0])

    @property
    def key_version(self) -> int:
        """The `key_version` stamped on rows written (or rotated) by this store."""
        return self._key_version

    # -- helpers ----------------------------------------------------------------------------

    def _encrypt(self, token: PaymentToken) -> bytes:
        payload = json.dumps({'payment_token_id': token.id, 'customer_id': token.customer_id})
        return self._fernet.encrypt(payload.encode())

    def _decrypt(self, ciphertext: bytes) -> str:
        try:
            payload = json.loads(self._fernet.decrypt(ciphertext))
        except (InvalidToken, ValueError) as error:
            raise VaultError('a stored token could not be decrypted') from error
        token_id = payload.get('payment_token_id') if isinstance(payload, dict) else None
        if not isinstance(token_id, str):
            raise VaultError('a stored token has an unexpected shape')
        return token_id

    @staticmethod
    async def _lock_owner(db: AsyncSession, owner_kind: str, owner_id: UUID) -> None:
        """Serialise writers for one owner until the transaction ends."""
        await db.execute(
            text('SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))'),
            {'key': f'vault:{owner_kind}:{owner_id}'},
        )

    @staticmethod
    async def _active_row(db: AsyncSession, owner_kind: str, owner_id: UUID) -> VaultToken | None:
        result = await db.execute(
            select(VaultToken)
            .where(
                VaultToken.owner_kind == owner_kind,
                VaultToken.owner_id == owner_id,
                VaultToken.deleted_at.is_(None),
            )
            .with_for_update()
        )
        return result.scalar_one_or_none()

    # -- public API -------------------------------------------------------------------------

    async def save(
        self,
        db: AsyncSession,
        owner_kind: str,
        owner_id: UUID,
        token: PaymentToken,
        actor: Actor,
    ) -> SaveResult:
        """Store `token` for the owner, superseding any active row, in the caller's transaction.

        A per-owner advisory lock makes two concurrent saves queue, so the partial unique index
        is never hit: the second save finds the first one's row and supersedes it. The caller
        commits. The ledger row (`vault.saved`) carries the payer id only.
        """
        await self._lock_owner(db, owner_kind, owner_id)
        previous = await self._active_row(db, owner_kind, owner_id)
        superseded: str | None = None
        if previous is not None:
            superseded = self._decrypt(previous.token_ciphertext)
            previous.deleted_at = datetime.now(UTC)
            await db.flush()
        row = VaultToken(
            owner_kind=owner_kind,
            owner_id=owner_id,
            payer_id=token.payer_id,
            token_ciphertext=self._encrypt(token),
            key_version=self._key_version,
        )
        db.add(row)
        await db.flush()
        await append_ledger_entry(
            db,
            action='vault.saved',
            actor_kind=actor.kind,
            actor_id=actor.id,
            detail={
                'owner_kind': owner_kind,
                'owner_id': str(owner_id),
                'payer_id': token.payer_id,
                'superseded': superseded is not None,
            },
        )
        return SaveResult(vault_token_id=row.id, superseded_payment_token_id=superseded)

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
        """Decrypt a token for a PayPal call and write the ledger row in the same transaction.

        Raises:
            VaultError: when the row is unknown or has been removed.
        """
        result = await db.execute(
            select(VaultToken)
            .where(VaultToken.id == vault_token_id, VaultToken.deleted_at.is_(None))
            .with_for_update()
        )
        row = result.scalar_one_or_none()
        if row is None:
            raise VaultError('no active saved PayPal for this vault token')
        token_id = self._decrypt(row.token_ciphertext)
        row.last_used_at = datetime.now(UTC)
        await append_ledger_entry(
            db,
            action='vault.token_used',
            actor_kind=actor_kind,
            actor_id=actor_id,
            trip_id=trip_id,
            request_id=request_id,
            detail={
                'purpose': purpose,
                'owner_kind': row.owner_kind,
                'owner_id': str(row.owner_id),
            },
        )
        return token_id

    async def remove(
        self, db: AsyncSession, owner_kind: str, owner_id: UUID, actor: Actor
    ) -> str | None:
        """Soft-delete the owner's active row and return its payment token id.

        The caller deletes the token at PayPal in the same transaction. Returns None (and writes
        nothing) when the owner has nothing saved.
        """
        await self._lock_owner(db, owner_kind, owner_id)
        row = await self._active_row(db, owner_kind, owner_id)
        if row is None:
            return None
        token_id = self._decrypt(row.token_ciphertext)
        row.deleted_at = datetime.now(UTC)
        await db.flush()
        await append_ledger_entry(
            db,
            action='vault.removed',
            actor_kind=actor.kind,
            actor_id=actor.id,
            detail={
                'owner_kind': owner_kind,
                'owner_id': str(owner_id),
                'payer_id': row.payer_id,
            },
        )
        return token_id

    async def status(self, db: AsyncSession, owner_kind: str, owner_id: UUID) -> bool:
        """True when the owner has an active saved token."""
        result = await db.execute(
            select(VaultToken.id).where(
                VaultToken.owner_kind == owner_kind,
                VaultToken.owner_id == owner_id,
                VaultToken.deleted_at.is_(None),
            )
        )
        return result.first() is not None

    async def rotate(self, db: AsyncSession) -> int:
        """Re-encrypt every row not yet under the newest key and return how many changed.

        Covers soft-deleted rows too, so no ciphertext is left under a key about to be dropped.
        The caller commits. Writes one `vault.rotated` ledger row when anything changed.
        """
        result = await db.execute(
            select(VaultToken).where(VaultToken.key_version != self._key_version).with_for_update()
        )
        rows = list(result.scalars())
        for row in rows:
            try:
                row.token_ciphertext = self._fernet.rotate(row.token_ciphertext)
            except InvalidToken as error:
                raise VaultError('a stored token could not be re-encrypted') from error
            row.key_version = self._key_version
        if rows:
            await db.flush()
            await append_ledger_entry(
                db,
                action='vault.rotated',
                actor_kind='system',
                actor_id=None,
                detail={'rows': len(rows), 'key_version': self._key_version},
            )
        return len(rows)

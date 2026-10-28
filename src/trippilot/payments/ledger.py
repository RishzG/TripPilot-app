"""Append-only money ledger.

Every money-adjacent action writes one row here, in the caller's transaction (so a rollback takes
the ledger row with it). The database rejects UPDATE, DELETE and TRUNCATE on the table (revision
0004). `detail` and `paypal_ids` must never carry a payment token id or a customer id.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from trippilot.payments.models import LedgerEntry

ActorKind = Literal['member', 'persona', 'system', 'script']


@dataclass(frozen=True)
class Actor:
    """Who caused a ledger row: a member, a demo persona, the system or a spike script."""

    kind: ActorKind
    id: str | None


async def append_ledger_entry(
    db: AsyncSession,
    *,
    action: str,
    actor_kind: ActorKind,
    actor_id: str | None,
    trip_id: UUID | None = None,
    request_id: str | None = None,
    paypal_ids: dict[str, Any] | None = None,
    amount_cents: int | None = None,
    detail: dict[str, Any] | None = None,
) -> int:
    """Append one ledger row in the caller's transaction and return its id.

    The caller commits (or rolls back) together with the action being recorded.
    """
    entry = LedgerEntry(
        action=action,
        actor_kind=actor_kind,
        actor_id=actor_id,
        trip_id=trip_id,
        request_id=request_id,
        paypal_ids=paypal_ids or {},
        amount_cents=amount_cents,
        detail=detail or {},
    )
    db.add(entry)
    await db.flush()
    return entry.id

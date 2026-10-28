"""Append-only money ledger (stub; implemented in the GREEN commit of plan 01-08)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

ActorKind = Literal['member', 'persona', 'system', 'script']


@dataclass(frozen=True)
class Actor:
    """Who caused a ledger row."""

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
    """Append one ledger row and return its id."""
    raise NotImplementedError

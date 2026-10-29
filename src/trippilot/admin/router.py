"""HTTP routes under /api/admin: team-only and read-only (plan 01-13, D-37).

Every route here is a GET guarded by `require_admin`, and none moves money; a test walks the
route table to keep it that way. Responses carry an allow-list of fields, never a ledger row's
free-form detail, so no token or customer id can leak (T-01-40).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select

from trippilot.admin.deps import AdminAccount, require_admin
from trippilot.auth.deps import DbSession
from trippilot.payments.models import LedgerEntry, WebhookEvent

router = APIRouter(prefix='/api/admin', tags=['admin'], dependencies=[Depends(require_admin)])

HOLD_ACTIONS = ('hold.placed', 'hold.captured', 'hold.voided', 'vault.token_used')
"""Ledger actions the Sandbox checks page shows."""

ROW_LIMIT = 50


class HoldRow(BaseModel):
    """One hold-related ledger row: what happened to which authorization."""

    ledger_id: int
    occurred_at: datetime
    action: str
    actor_kind: str
    request_id: str | None
    authorization_id: str | None
    status: str | None
    amount_cents: int | None
    expires_at: str | None


class WebhookRow(BaseModel):
    """One received PayPal webhook."""

    event_id: str
    event_type: str
    resource_id: str | None
    verification_status: str
    received_at: datetime
    processed_at: datetime | None


class SandboxChecks(BaseModel):
    """The latest hold ledger rows and webhook events, newest first."""

    holds: list[HoldRow]
    webhooks: list[WebhookRow]


def _text(source: dict[str, Any], key: str) -> str | None:
    """Return `source[key]` when it is a string, else None."""
    value = source.get(key)
    return value if isinstance(value, str) else None


@router.get('/sandbox-checks')
async def sandbox_checks(_admin: AdminAccount, db: DbSession) -> SandboxChecks:
    """Return the latest 50 hold ledger rows and 50 webhook events (read-only)."""
    ledger = await db.scalars(
        select(LedgerEntry)
        .where(LedgerEntry.action.in_(HOLD_ACTIONS))
        .order_by(LedgerEntry.id.desc())
        .limit(ROW_LIMIT)
    )
    events = await db.scalars(
        select(WebhookEvent).order_by(WebhookEvent.received_at.desc()).limit(ROW_LIMIT)
    )
    holds = [
        HoldRow(
            ledger_id=entry.id,
            occurred_at=entry.occurred_at,
            action=entry.action,
            actor_kind=entry.actor_kind,
            request_id=entry.request_id,
            authorization_id=_text(entry.paypal_ids, 'authorization_id'),
            status=_text(entry.detail, 'status'),
            amount_cents=entry.amount_cents,
            expires_at=_text(entry.detail, 'expiration_time'),
        )
        for entry in ledger
    ]
    webhooks = [
        WebhookRow(
            event_id=event.event_id,
            event_type=event.event_type,
            resource_id=event.resource_id,
            verification_status=event.verification_status,
            received_at=event.received_at,
            processed_at=event.processed_at,
        )
        for event in events
    ]
    return SandboxChecks(holds=holds, webhooks=webhooks)

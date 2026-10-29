"""Background tasks owned by the payments package.

Plan 01-21 owns this seam. 01-13 adds `process_webhook_event`; 01-24 lists this module in the
worker's import paths so the tasks are registered with the procrastinate app.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import structlog

from trippilot.db.engine import get_engine, session_factory
from trippilot.jobs.app import app
from trippilot.payments.ledger import append_ledger_entry
from trippilot.payments.models import WebhookEvent

logger = structlog.get_logger(__name__)

WEBHOOK_QUEUE = 'webhooks'
WEBHOOK_RECEIVED = 'webhook.received'
"""Ledger action written when a verified webhook has been processed."""


@app.task(name='payments.process_webhook_event', queue=WEBHOOK_QUEUE)
async def process_webhook_event(webhook_event_id: str) -> None:
    """Record a stored webhook as processed: summary, `processed_at` and one ledger row.

    Phase 1 only records the event; later phases re-fetch the PayPal resource here and reconcile
    (the payload is never trusted alone). It moves no money. Running it again for the same event
    is a no-op, so a retried job cannot double-record.
    """
    get_engine()
    async with session_factory() as session:
        event = await session.get(WebhookEvent, uuid.UUID(webhook_event_id), with_for_update=True)
        if event is None:
            logger.warning('webhook_event_missing', webhook_event_id=webhook_event_id)
            return
        if event.processed_at is not None:
            return
        event_id, event_type = event.event_id, event.event_type
        status = event.summary.get('status')
        event.summary = {'resource_id': event.resource_id, 'status': status}
        event.processed_at = datetime.now(UTC)
        paypal_ids = {'event_id': event_id}
        if event.resource_id is not None:
            paypal_ids['resource_id'] = event.resource_id
        await append_ledger_entry(
            session,
            action=WEBHOOK_RECEIVED,
            actor_kind='system',
            actor_id=None,
            paypal_ids=paypal_ids,
            detail={'event_type': event_type, 'status': status},
        )
        await session.commit()
    logger.info('webhook_event_processed', event_id=event_id, event_type=event_type)

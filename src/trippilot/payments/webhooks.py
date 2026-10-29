"""PayPal webhook receiver: verify, store once, defer a processing job (plan 01-13, D-32).

Anyone can POST here, so every delivery is checked with PayPal's verify-webhook-signature using the
exact bytes that arrived and this environment's webhook id (T-01-37). Only verified deliveries are
stored, unique on PayPal's event id, and a job is deferred only when the insert created the row
(T-01-38). The route answers fast: processing happens in the worker, and nothing here moves money.
"""

from __future__ import annotations

import json
import logging
from typing import Annotated, Any

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Request, status
from procrastinate.exceptions import ProcrastinateException
from pydantic import BaseModel
from sqlalchemy.dialects.postgresql import insert

from trippilot.auth.deps import AppSettings, DbSession
from trippilot.contracts.paypal import PayPalError, PayPalGateway
from trippilot.payments import get_paypal_gateway
from trippilot.payments.models import WebhookEvent
from trippilot.payments.tasks import process_webhook_event

log = logging.getLogger(__name__)

router = APIRouter()

VERIFIED = 'SUCCESS'
"""`webhook_events.verification_status` for a delivery PayPal confirmed (RESEARCH A6)."""

Gateway = Annotated[PayPalGateway, Depends(get_paypal_gateway)]


class WebhookAck(BaseModel):
    """The empty acknowledgement PayPal needs to stop retrying."""

    received: bool = True


def _paypal_headers(request: Request) -> dict[str, str]:
    """Return the `paypal-*` signature headers of the delivery (names lowercased)."""
    return {
        name.lower(): value
        for name, value in request.headers.items()
        if name.lower().startswith('paypal-')
    }


def _text(value: object) -> str | None:
    """Return the value when it is a non-empty string, else None."""
    return value if isinstance(value, str) and value else None


@router.post(
    '/webhooks',
    responses={
        400: {'description': 'The delivery could not be verified or is not a PayPal event.'},
        503: {'description': 'No webhook id is configured, or PayPal could not be asked.'},
    },
)
async def receive_webhook(
    request: Request, db: DbSession, gateway: Gateway, settings: AppSettings
) -> WebhookAck:
    """Verify a PayPal delivery, store it once and defer its processing job."""
    if not settings.paypal_webhook_id:
        log.error('webhook received but PAYPAL_WEBHOOK_ID is not configured')
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, 'webhook_unavailable')

    raw = await request.body()  # the unmodified bytes: PayPal verifies exactly what it sent
    try:
        verified = await gateway.verify_webhook_signature(
            headers=_paypal_headers(request), raw_body=raw, webhook_id=settings.paypal_webhook_id
        )
    except PayPalError as error:
        # PayPal could not be asked: a non-2xx answer makes PayPal redeliver later.
        log.warning('webhook verification call failed: %s', error.summary())
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, 'verification_unavailable'
        ) from error
    if not verified:
        log.warning('webhook delivery failed signature verification')
        raise HTTPException(status.HTTP_400_BAD_REQUEST, 'verification_failed')

    try:
        event: Any = json.loads(raw)
    except ValueError as error:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, 'malformed_event') from error
    event_id = _text(event.get('id')) if isinstance(event, dict) else None
    event_type = _text(event.get('event_type')) if isinstance(event, dict) else None
    if event_id is None or event_type is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, 'malformed_event')
    resource = event.get('resource')
    resource = resource if isinstance(resource, dict) else {}
    resource_status = _text(resource.get('status'))

    created = await db.execute(
        insert(WebhookEvent)
        .values(
            event_id=event_id,
            event_type=event_type,
            resource_type=_text(event.get('resource_type')),
            resource_id=_text(resource.get('id')),
            verification_status=VERIFIED,
            summary={'status': resource_status},
        )
        .on_conflict_do_nothing(index_elements=[WebhookEvent.event_id])
        .returning(WebhookEvent.id)
    )
    row_id = created.scalar_one_or_none()
    await db.commit()
    if row_id is None:
        log.info('webhook %s (%s) was already received', event_id, event_type)
        return WebhookAck()

    log.info('webhook %s (%s) stored', event_id, event_type)
    try:
        await process_webhook_event.defer_async(webhook_event_id=str(row_id))
    except (ProcrastinateException, psycopg.Error):
        # The row is durable and PayPal must not retry (a redelivery is a no-op by design), so
        # answer 200; the unprocessed row stays visible on the Sandbox checks page.
        log.exception('could not defer processing of webhook %s', event_id)
    return WebhookAck()

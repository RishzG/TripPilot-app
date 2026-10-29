"""Background tasks owned by the payments package.

Plan 01-21 owns this seam. 01-13 adds `process_webhook_event`; 01-24 lists this module in the
worker's import paths so the tasks are registered with the procrastinate app.
"""

from __future__ import annotations

from trippilot.jobs.app import app

WEBHOOK_QUEUE = 'webhooks'


@app.task(name='payments.process_webhook_event', queue=WEBHOOK_QUEUE)
async def process_webhook_event(webhook_event_id: str) -> None:
    """Skeleton so the module imports; the behaviour lands with the implementation commit."""

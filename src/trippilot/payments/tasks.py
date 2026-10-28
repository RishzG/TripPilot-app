"""Background tasks owned by the payments package. No tasks are registered yet.

Plan 01-21 owns this seam. 01-13 adds `process_webhook_event`; 01-24 lists this module in the
worker's import paths so the tasks are registered with the procrastinate app.
"""

from __future__ import annotations

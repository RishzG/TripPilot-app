"""HTTP routes under /api/paypal. Mounted by app.py; this module registers no routes yet.

Plan 01-21 owns this seam. 01-08 adds the vault routes (each with the `CurrentAccount`
dependency), 01-13 includes the webhook router, 01-14 adds the pool routes.
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix='/api/paypal', tags=['paypal'])

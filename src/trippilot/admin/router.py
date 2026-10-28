"""HTTP routes under /api/admin. Mounted by app.py; this module registers no routes yet.

Plan 01-21 owns this seam. 01-13 adds the admin routes, each guarded by `require_admin`.
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix='/api/admin', tags=['admin'])

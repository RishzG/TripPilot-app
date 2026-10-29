"""Origin check for state-changing API requests (T-01-35, T-01-64).

Session cookies are SameSite=Lax, which already keeps them off cross-site POSTs; this middleware
is the second layer. A POST, PUT, PATCH or DELETE under `/api` whose `Origin` (or, when `Origin`
is absent, `Referer`) is not an allowed origin is answered 403 before any route runs. Requests
carrying neither header come from non-browser clients (the smoke script, tests); browsers always
send `Origin` on cross-site unsafe requests, so they are let through.

The PayPal webhook path is exempt: PayPal does not send our origin, and that route is protected by
signature verification instead (plan 01-13).
"""

from __future__ import annotations

from urllib.parse import urlsplit

from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from trippilot.settings import Settings

WEBHOOK_PATH = '/api/paypal/webhooks'
UNSAFE_METHODS = frozenset({'POST', 'PUT', 'PATCH', 'DELETE'})
VITE_DEV_ORIGINS = frozenset({'http://localhost:5173', 'http://127.0.0.1:5173'})
"""The Vite dev server's origins; accepted only when APP_ENV is local (the dev SPA proxies /api)."""


def origin_of(url: str) -> str | None:
    """Return `scheme://host[:port]` (lowercased) for a URL, or None when it has no origin.

    `Origin: null` and any malformed value yield None, which is never an allowed origin.
    """
    parts = urlsplit(url)
    if not parts.scheme or not parts.netloc:
        return None
    return f'{parts.scheme.lower()}://{parts.netloc.lower()}'


def allowed_origins(settings: Settings) -> frozenset[str]:
    """Return the origins that may send unsafe API requests for these settings.

    The public base URL always; the Vite dev origins only when `app_env` is `local`, so staging
    and production never accept them.
    """
    allowed: set[str] = set()
    public = origin_of(settings.public_base_url)
    if public is not None:
        allowed.add(public)
    if settings.app_env == 'local':
        allowed |= VITE_DEV_ORIGINS
    return frozenset(allowed)


class OriginCheckMiddleware:
    """Pure ASGI middleware refusing unsafe `/api` requests from a foreign origin with 403."""

    def __init__(self, app: ASGIApp, *, allowed_origins: frozenset[str]) -> None:
        """Wrap `app`; `allowed_origins` comes from `allowed_origins(settings)`."""
        self._app = app
        self._allowed = allowed_origins

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Pass the request on, or answer 403 when its Origin or Referer is not allowed."""
        if scope['type'] != 'http' or not self._is_checked(scope):
            await self._app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        claimed = headers.get('origin')
        if claimed is None:
            claimed = headers.get('referer')
        if claimed is None or origin_of(claimed) in self._allowed:
            await self._app(scope, receive, send)
            return
        refusal = JSONResponse({'detail': 'Cross-site request refused'}, status_code=403)
        await refusal(scope, receive, send)

    @staticmethod
    def _is_checked(scope: Scope) -> bool:
        """Return True for an unsafe method on an `/api` path other than the webhook endpoint."""
        path: str = scope['path']
        if scope['method'] not in UNSAFE_METHODS:
            return False
        if path != '/api' and not path.startswith('/api/'):
            return False
        return path.rstrip('/') != WEBHOOK_PATH

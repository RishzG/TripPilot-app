"""FastAPI application factory."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response

from trippilot import health
from trippilot.db.engine import configure_event_loop_policy
from trippilot.log_config import configure_logging
from trippilot.settings import Settings, get_settings

_PAYPAL_ORIGINS = (
    'https://www.sandbox.paypal.com https://www.paypalobjects.com https://api-m.sandbox.paypal.com'
)
CSP_REPORT_ONLY = (
    "default-src 'self'; "
    f"script-src 'self' {_PAYPAL_ORIGINS}; "
    f"frame-src 'self' {_PAYPAL_ORIGINS}; "
    f"connect-src 'self' {_PAYPAL_ORIGINS}; "
    f"img-src 'self' data: {_PAYPAL_ORIGINS}; "
    "style-src 'self' 'unsafe-inline'"
)
"""Report-only CSP allowing self plus the PayPal sandbox origins (Pitfall 13)."""

SECURITY_HEADERS = {
    'Referrer-Policy': 'no-referrer',
    'X-Frame-Options': 'DENY',
    'X-Content-Type-Options': 'nosniff',
    'Content-Security-Policy-Report-Only': CSP_REPORT_ONLY,
}
"""Headers set on every response (threat T-01-05)."""


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the FastAPI app.

    Args:
        settings: Optional settings override (used by the OpenAPI dump); runtime callers pass
            nothing and get `get_settings()`.
    """
    resolved = settings if settings is not None else get_settings()
    configure_logging()
    configure_event_loop_policy()

    app = FastAPI(title='TripPilot', version='0.1.0')
    app.state.settings = resolved

    @app.middleware('http')
    async def add_security_headers(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        """Attach the security headers to every response."""
        response = await call_next(request)
        for name, value in SECURITY_HEADERS.items():
            response.headers[name] = value
        return response

    app.include_router(health.router)
    return app

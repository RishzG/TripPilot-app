"""FastAPI application factory."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response

from trippilot import health
from trippilot.admin import router as admin_router
from trippilot.auth import router as auth_router
from trippilot.db.engine import configure_event_loop_policy
from trippilot.demo import router as demo_router
from trippilot.jobs.app import app as jobs_app
from trippilot.log_config import configure_logging
from trippilot.payments import router as payments_router
from trippilot.settings import Settings, get_settings
from trippilot.trips import router as trips_router
from trippilot.web_static import default_dist_dir, mount_spa

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


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Open the procrastinate app so web code can defer jobs, and close it on shutdown."""
    async with jobs_app.open_async():
        yield


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the FastAPI app.

    Args:
        settings: Optional settings override (used by the OpenAPI dump); runtime callers pass
            nothing and get `get_settings()`.
    """
    resolved = settings if settings is not None else get_settings()
    configure_logging()
    configure_event_loop_policy()

    app = FastAPI(title='TripPilot', version='0.1.0', lifespan=lifespan)
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
    app.include_router(auth_router.router)
    app.include_router(trips_router.router)
    app.include_router(payments_router.router)
    app.include_router(admin_router.router)
    if resolved.demo_mode:
        # D-15: the persona routes are not mounted at all unless DEMO_MODE is on (404 otherwise).
        app.include_router(demo_router.router)
    mount_spa(app, default_dist_dir())  # last: the catch-all must never shadow an API route
    return app

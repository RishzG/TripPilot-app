"""Local-only browser fixture for a suite that exceeds the per-address invite quota.

Use this factory only with a disposable *_preview or *_test database. Domain authorization
and CSRF remain enabled; backend integration tests cover the real invite limiter.
"""

from urllib.parse import urlsplit

from fastapi import FastAPI
from sqlalchemy.engine import make_url

from trippilot.app import create_app
from trippilot.settings import get_settings
from trippilot.trips.invites import invite_rate_limit


def create_browser_app() -> FastAPI:
    """Disable only the invite quota, guarded against shared/production environments."""
    settings = get_settings()
    name = make_url(settings.database_url).database or ''
    if (
        settings.app_env not in ('local', 'test')
        or not name.endswith(('_preview', '_test'))
        or urlsplit(settings.public_base_url).hostname not in ('localhost', '127.0.0.1')
    ):
        raise RuntimeError('Browser fixture requires local/test settings and a disposable database')
    app = create_app(settings)
    app.dependency_overrides[invite_rate_limit] = lambda: None
    return app

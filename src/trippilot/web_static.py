"""Serve the built SPA from the API's own origin (one image, no CORS, no cross-site cookies).

`mount_spa` is registered after every API route. Static build files and the SPA shell answer
non-/api GETs; anything under /api that matches no route stays a JSON 404 so a mistyped API call
can never be mistaken for a page (threat T-01-59).
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import FileResponse, JSONResponse
from starlette.routing import Match, Route
from starlette.staticfiles import StaticFiles
from starlette.types import Scope

DIST_ENV_VAR = 'WEB_DIST_DIR'
"""Environment variable naming the build directory (the Docker image sets it explicitly)."""

_API_PREFIX = 'api'
_ALL_METHODS = ['GET', 'HEAD', 'POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS']


def default_dist_dir() -> Path:
    """Return the SPA build directory: `$WEB_DIST_DIR`, else `web/dist` beside the source tree."""
    configured = os.environ.get(DIST_ENV_VAR)
    if configured:
        return Path(configured)
    return Path(__file__).resolve().parents[2] / 'web' / 'dist'


def _is_api_path(path: str) -> bool:
    """True for `api` and anything beneath `api/` (path is relative, no leading slash)."""
    return path == _API_PREFIX or path.startswith(f'{_API_PREFIX}/')


class _ApiNotFoundRoute(Route):
    """Catch-all for /api paths that matches only partially, whatever the method.

    A partial match loses to any full match (real routes) and, being registered before the
    shell route, wins over the shell's own GET-only partial match. So a missing API path is a
    404 for every method (the D-15 fence), while a wrong method on a real route keeps its 405.
    """

    def matches(self, scope: Scope) -> tuple[Match, Scope]:
        """Report a full match as a partial one."""
        match, child_scope = super().matches(scope)
        return (Match.PARTIAL if match == Match.FULL else match), child_scope


def mount_spa(app: FastAPI, dist_dir: Path) -> None:
    """Mount the SPA build onto `app`; do nothing when `dist_dir` has no index.html.

    Args:
        app: The application, with every API route already registered.
        dist_dir: The Vite build output (index.html plus an optional assets directory).
    """
    index = dist_dir / 'index.html'
    if not index.is_file():
        return
    root = dist_dir.resolve()

    assets = dist_dir / 'assets'
    if assets.is_dir():
        app.mount('/assets', StaticFiles(directory=assets), name='spa-assets')

    async def api_not_found(_request: Request) -> JSONResponse:
        """Answer an unmatched /api path with a JSON 404, never the SPA shell."""
        return JSONResponse({'detail': 'Not Found'}, status_code=status.HTTP_404_NOT_FOUND)

    for path in ('/api/{rest:path}', '/api'):
        app.router.routes.append(_ApiNotFoundRoute(path, api_not_found, methods=_ALL_METHODS))

    @app.get('/{full_path:path}', include_in_schema=False)
    async def spa(full_path: str) -> FileResponse:
        """Answer a non-/api GET with the matching build file, else the SPA shell."""
        if _is_api_path(full_path):
            raise HTTPException(status.HTTP_404_NOT_FOUND, 'Not Found')
        candidate = (root / full_path).resolve()
        if candidate.is_file() and candidate.is_relative_to(root):
            return FileResponse(candidate)
        return FileResponse(index)

"""Unit tests for the SPA mount: index.html fallback, /assets, 404 JSON under /api, no-op."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

from trippilot.web_static import mount_spa

INDEX_HTML = '<!doctype html><html><body><div id="root"></div></body></html>'
ASSET_JS = 'console.log("spa");'


def _make_dist(root: Path, *, with_index: bool = True) -> Path:
    """Create a dist directory shaped like a Vite build and return it."""
    dist = root / 'dist'
    (dist / 'assets').mkdir(parents=True)
    (dist / 'assets' / 'app.js').write_text(ASSET_JS, encoding='utf-8')
    (dist / 'favicon.svg').write_text('<svg/>', encoding='utf-8')
    if with_index:
        (dist / 'index.html').write_text(INDEX_HTML, encoding='utf-8')
    return dist


async def _client(dist: Path) -> httpx.AsyncClient:
    """Return a client for a bare FastAPI app with one /api route and the SPA mounted last."""
    app = FastAPI()

    @app.get('/api/ping')
    async def ping() -> dict[str, str]:
        return {'pong': 'yes'}

    mount_spa(app, dist)
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test')


@pytest.fixture
async def spa_client(tmp_path: Path) -> AsyncIterator[httpx.AsyncClient]:
    """A client against an app with a complete dist mounted."""
    async with await _client(_make_dist(tmp_path)) as http_client:
        yield http_client


@pytest.mark.parametrize('path', ['/', '/trips/abc', '/demo', '/trips/new'])
async def test_non_api_gets_return_index_html(spa_client: httpx.AsyncClient, path: str) -> None:
    """Client-side routes are answered with the SPA shell."""
    response = await spa_client.get(path)

    assert response.status_code == 200
    assert response.text == INDEX_HTML
    assert response.headers['content-type'].startswith('text/html')


async def test_assets_are_served(spa_client: httpx.AsyncClient) -> None:
    """Files under /assets come from the build, not the HTML fallback."""
    response = await spa_client.get('/assets/app.js')

    assert response.status_code == 200
    assert response.text == ASSET_JS


async def test_missing_asset_is_a_404_not_the_shell(spa_client: httpx.AsyncClient) -> None:
    """A stale hashed asset name must not be answered with index.html."""
    response = await spa_client.get('/assets/gone.js')

    assert response.status_code == 404
    assert 'id="root"' not in response.text


async def test_top_level_build_files_are_served(spa_client: httpx.AsyncClient) -> None:
    """A real file at the dist root (a favicon) is served as itself."""
    response = await spa_client.get('/favicon.svg')

    assert response.status_code == 200
    assert response.text == '<svg/>'


async def test_unknown_api_path_is_404_json(spa_client: httpx.AsyncClient) -> None:
    """An unmatched /api path never falls through to index.html."""
    for path in ('/api/nope', '/api/trips/does/not/exist', '/api'):
        response = await spa_client.get(path)

        assert response.status_code == 404, path
        assert response.headers['content-type'].startswith('application/json'), path
        assert 'id="root"' not in response.text, path
        assert 'detail' in response.json(), path


async def test_real_api_route_still_answers(spa_client: httpx.AsyncClient) -> None:
    """The mount is registered last, so routes added before it keep working."""
    response = await spa_client.get('/api/ping')

    assert response.status_code == 200
    assert response.json() == {'pong': 'yes'}


async def test_paths_cannot_escape_the_dist_directory(tmp_path: Path) -> None:
    """A traversal attempt never returns a file outside dist."""
    (tmp_path / 'secret.txt').write_text('top secret', encoding='utf-8')
    async with await _client(_make_dist(tmp_path)) as http_client:
        for path in ('/..%2fsecret.txt', '/%2e%2e/secret.txt', '/assets/..%2f..%2fsecret.txt'):
            response = await http_client.get(path)

            assert 'top secret' not in response.text, path


async def test_without_index_html_nothing_is_mounted(tmp_path: Path) -> None:
    """A dist directory with no index.html registers no routes, so GET / is a plain 404."""
    async with await _client(_make_dist(tmp_path, with_index=False)) as http_client:
        root = await http_client.get('/')
        asset = await http_client.get('/assets/app.js')
        api = await http_client.get('/api/ping')

    assert root.status_code == 404
    assert asset.status_code == 404
    assert api.status_code == 200


async def test_a_missing_dist_directory_is_a_no_op(tmp_path: Path) -> None:
    """Running from a source checkout with no build leaves the API untouched."""
    async with await _client(tmp_path / 'not-built') as http_client:
        assert (await http_client.get('/')).status_code == 404
        assert (await http_client.get('/api/ping')).status_code == 200

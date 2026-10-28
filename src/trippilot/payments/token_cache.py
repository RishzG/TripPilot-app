"""Shared client-credentials token cache for the PayPal REST API.

PayPal reuses one access token until it expires (about nine hours) and fixes its permissions
when it is issued, so a token issued before a dashboard feature change keeps the old scopes.
The cure (design-notes 2026-10-22) is to terminate the token and request a new one, which
`terminate` does; `PayPalClient` calls it once on a 401 or a 403 `NOT_AUTHORIZED`.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable

import httpx
from pydantic import SecretStr

from trippilot.contracts.paypal import PayPalError

EXPIRY_MARGIN_SECONDS = 60.0
"""A cached token is refreshed this long before PayPal says it expires."""


def _decode(response: httpx.Response) -> object:
    """Decode a JSON body, returning None for an empty or non-JSON body."""
    try:
        return response.json()
    except ValueError:
        return None


class TokenCache:
    """One async-safe client-credentials token per app credentials."""

    def __init__(
        self,
        http: httpx.AsyncClient,
        base_url: str,
        client_id: str,
        client_secret: SecretStr,
        clock: Callable[[], float] | None = None,
    ) -> None:
        """Bind the cache to an HTTP client and credentials; `clock` is injectable for tests."""
        self._http = http
        self._base_url = base_url.rstrip('/')
        self._auth = (client_id, client_secret.get_secret_value())
        self._clock: Callable[[], float] = clock or time.monotonic
        self._lock = asyncio.Lock()
        self._token: str | None = None
        self._expires_at = 0.0
        self._scopes: tuple[str, ...] = ()

    @property
    def scopes(self) -> tuple[str, ...]:
        """The scopes granted to the most recently issued token (empty before the first fetch)."""
        return self._scopes

    async def get(self) -> str:
        """Return a valid access token, fetching a new one when none is cached or it is stale."""
        async with self._lock:
            if self._token is not None and self._clock() < self._expires_at - EXPIRY_MARGIN_SECONDS:
                return self._token
            return await self._fetch()

    async def _fetch(self) -> str:
        """Request a client-credentials token and cache it. The caller holds the lock."""
        response = await self._http.post(
            f'{self._base_url}/v1/oauth2/token',
            auth=self._auth,
            data={'grant_type': 'client_credentials'},
        )
        body = _decode(response)
        if not response.is_success:
            raise PayPalError.from_body(response.status_code, body)
        if not isinstance(body, dict) or not isinstance(body.get('access_token'), str):
            raise PayPalError(response.status_code, 'MALFORMED_TOKEN_RESPONSE')
        self._token = str(body['access_token'])
        self._expires_at = self._clock() + float(body.get('expires_in') or 0)
        self._scopes = tuple(str(body.get('scope') or '').split())
        return self._token

    async def terminate(self, stale: str | None = None) -> bool:
        """Terminate the cached token at PayPal and clear it, so the next `get` issues a new one.

        When `stale` is given and the cache already holds a different token (another caller
        refreshed first), nothing is terminated. Returns True when PayPal accepted the call.
        """
        async with self._lock:
            token = self._token
            if token is None or (stale is not None and stale != token):
                return False
            self._token = None
            self._expires_at = 0.0
            self._scopes = ()
            response = await self._http.post(
                f'{self._base_url}/v1/oauth2/token/terminate',
                auth=self._auth,
                data={'token': token, 'token_type_hint': 'ACCESS_TOKEN'},
            )
            return response.is_success

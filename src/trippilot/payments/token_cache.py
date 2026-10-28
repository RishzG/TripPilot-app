"""Shared client-credentials token cache (RED stub)."""

from __future__ import annotations

from collections.abc import Callable

import httpx
from pydantic import SecretStr


class TokenCache:
    """Stub: not implemented yet."""

    def __init__(
        self,
        http: httpx.AsyncClient,
        base_url: str,
        client_id: str,
        client_secret: SecretStr,
        clock: Callable[[], float] | None = None,
    ) -> None:
        """Stub constructor."""
        self.scopes: tuple[str, ...] = ()

    async def get(self) -> str:
        """Stub: not implemented yet."""
        raise NotImplementedError

    async def terminate(self, stale: str | None = None) -> bool:
        """Stub: not implemented yet."""
        raise NotImplementedError

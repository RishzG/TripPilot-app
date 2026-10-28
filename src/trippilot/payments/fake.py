"""In-memory PayPal gateway double (RED stub)."""

from __future__ import annotations

from trippilot.contracts.paypal import PayPalError


class FakePayPal:
    """Stub: nothing implemented yet."""

    def __init__(self) -> None:
        """Stub constructor."""
        self.calls: list[tuple[str, dict[str, object]]] = []
        self.webhook_verdict = True

    def fail_next(self, method: str, error: PayPalError) -> None:
        """Stub: not implemented yet."""
        raise NotImplementedError

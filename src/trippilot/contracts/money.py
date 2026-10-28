"""Integer-cents money type and the PayPal decimal-string boundary (RED stubs)."""

from __future__ import annotations

from typing import NewType

Cents = NewType('Cents', int)
"""An amount of money in integer US cents; never a float or Decimal inside the app."""


def to_paypal_value(cents: Cents) -> str:
    """Stub: not implemented yet."""
    return ''


def from_paypal_value(value: str) -> Cents:
    """Stub: not implemented yet."""
    return Cents(-1)

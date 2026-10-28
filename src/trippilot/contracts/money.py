"""Integer-cents money type and the PayPal decimal-string boundary.

Money is held as integer US cents everywhere inside the app. A two-decimal string such as
`'12.34'` exists only at the PayPal HTTP boundary, and the conversion uses integer arithmetic
only (no float or Decimal maths) so rounding bugs cannot appear.
"""

from __future__ import annotations

import re
from typing import NewType

Cents = NewType('Cents', int)
"""An amount of money in integer US cents; never a float or Decimal inside the app."""

_PAYPAL_VALUE = re.compile(r'[0-9]+\.[0-9]{2}')


def to_paypal_value(cents: Cents) -> str:
    """Format a non-negative cent amount as PayPal's two-decimal string.

    Raises `ValueError` for a negative amount.
    """
    if cents < 0:
        raise ValueError(f'amount must be non-negative, got {cents} cents')
    whole, fraction = divmod(int(cents), 100)
    return f'{whole}.{fraction:02d}'


def from_paypal_value(value: str) -> Cents:
    """Parse PayPal's strict two-decimal amount string into integer cents.

    Raises `ValueError` unless the string is digits, a dot, and exactly two digits.
    """
    if not _PAYPAL_VALUE.fullmatch(value):
        raise ValueError(f'not a two-decimal amount string: {value!r}')
    whole, fraction = value.split('.')
    return Cents(int(whole) * 100 + int(fraction))

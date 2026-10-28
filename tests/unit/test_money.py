"""Tests for the integer-cents money boundary (contracts.money)."""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from trippilot.contracts.money import Cents, from_paypal_value, to_paypal_value


@pytest.mark.parametrize(
    ('cents', 'expected'),
    [(0, '0.00'), (5, '0.05'), (50, '0.50'), (100, '1.00'), (123456, '1234.56')],
)
def test_to_paypal_value_formats_two_decimals(cents: int, expected: str) -> None:
    assert to_paypal_value(Cents(cents)) == expected


def test_to_paypal_value_rejects_negative() -> None:
    with pytest.raises(ValueError, match='non-negative'):
        to_paypal_value(Cents(-1))


def test_from_paypal_value_parses_two_decimal_string() -> None:
    assert from_paypal_value('12.30') == 1230
    assert from_paypal_value('0.05') == 5


@pytest.mark.parametrize('bad', ['1.2', 'abc', '', '1', '1.234', '-1.00', ' 1.00', '1.00\n'])
def test_from_paypal_value_rejects_malformed(bad: str) -> None:
    with pytest.raises(ValueError, match='two-decimal'):
        from_paypal_value(bad)


@given(st.integers(min_value=0, max_value=10**9 - 1))
def test_round_trip_for_every_non_negative_cent_amount(cents: int) -> None:
    assert from_paypal_value(to_paypal_value(Cents(cents))) == cents

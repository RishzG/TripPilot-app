"""Deliberately failing canary used to prove that a failing check blocks merge. Never merged."""


def test_gate_canary_fails_on_purpose() -> None:
    """Fail so the backend check goes red."""
    assert 1 + 1 == 3

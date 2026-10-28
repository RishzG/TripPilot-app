"""Staging power tool (01-07). RED-phase scaffold: the behaviour lands in the GREEN commit."""

from __future__ import annotations

import subprocess
from collections.abc import Callable, Mapping, Sequence

GH_REPO_DEFAULT = 'RishzG/TripPilot-app'


def main(
    argv: Sequence[str],
    *,
    env: Mapping[str, str] | None = None,
    runner: Callable[[Sequence[str]], subprocess.CompletedProcess[str]] | None = None,
    sleep: Callable[[float], None] | None = None,
    monotonic: Callable[[], float] | None = None,
) -> int:
    """Not implemented yet."""
    raise NotImplementedError

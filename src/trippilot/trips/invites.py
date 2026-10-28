"""Reusable invite links (D-21): RED-phase stub, replaced by the real module in the GREEN commit."""

from __future__ import annotations

from fastapi import Request


async def invite_rate_limit(request: Request) -> None:
    """Per-IP limiter for the invite routes (stub)."""
    raise NotImplementedError

"""The fixed cast of six simulated friends (D-19). Later phases script against these slugs."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Persona:
    """A simulated friend: stable slug, display name, avatar key and a short persona note."""

    slug: str
    name: str
    avatar_key: str
    note: str


CAST: tuple[Persona, ...] = (
    Persona('maya', 'Maya', 'maya', 'tight budget'),
    Persona('sam', 'Sam', 'sam', 'wants adventure'),
    Persona('ana', 'Ana', 'ana', 'foodie, flexible dates'),
    Persona('leo', 'Leo', 'leo', 'last-minute planner'),
    Persona('priya', 'Priya', 'priya', 'organised, loves cabins'),
    Persona('jules', 'Jules', 'jules', 'joins late, easygoing'),
)
"""The avatar keys equal the slugs: they are the first six `ILLUSTRATED_AVATAR_KEYS` (UI-SPEC)."""


def find_persona(slug: str) -> Persona | None:
    """Return the persona with this slug, or None."""
    return next((persona for persona in CAST if persona.slug == slug), None)

"""Declarative base with a constraint naming convention for every mapped table."""

from __future__ import annotations

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

NAMING_CONVENTION = {
    'ix': 'ix_%(column_0_label)s',
    'uq': 'uq_%(table_name)s_%(column_0_name)s',
    'ck': 'ck_%(table_name)s_%(constraint_name)s',
    'fk': 'fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s',
    'pk': 'pk_%(table_name)s',
}
"""Deterministic constraint names, so any future autogenerate or manual revision stays stable."""


class Base(DeclarativeBase):
    """Base class of every ORM model; the schema itself is owned by the Alembic revisions."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)

"""ORM models for the 0001_skeleton auth tables: accounts, sessions and oauth_states."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, LargeBinary, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from trippilot.db.base import Base


class Account(Base):
    """A person: a real member (keyed on the PayPal subject) or a demo persona (D-13)."""

    __tablename__ = 'accounts'

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text('gen_random_uuid()')
    )
    kind: Mapped[str] = mapped_column(Text, server_default='member')
    paypal_subject: Mapped[str | None] = mapped_column(Text, unique=True)
    persona_slug: Mapped[str | None] = mapped_column(Text, unique=True)
    email: Mapped[str | None] = mapped_column(Text)
    display_name: Mapped[str] = mapped_column(Text)
    nickname: Mapped[str | None] = mapped_column(Text)
    avatar_kind: Mapped[str] = mapped_column(Text, server_default='initials')
    avatar_key: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(server_default=text('now()'))


class SessionRow(Base):
    """One signed-in browser. The primary key is sha256 of the cookie value, never the value."""

    __tablename__ = 'sessions'

    id_hash: Mapped[bytes] = mapped_column(LargeBinary, primary_key=True)
    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey('accounts.id', ondelete='CASCADE')
    )
    created_at: Mapped[datetime] = mapped_column(server_default=text('now()'))
    last_seen_at: Mapped[datetime] = mapped_column(server_default=text('now()'))
    expires_at: Mapped[datetime]
    user_agent: Mapped[str | None] = mapped_column(Text)
    is_persona: Mapped[bool] = mapped_column(server_default=text('false'))


class OAuthState(Base):
    """A single-use Log in with PayPal state row (used from plan 01-12)."""

    __tablename__ = 'oauth_states'

    state_hash: Mapped[bytes] = mapped_column(LargeBinary, primary_key=True)
    invite_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    next_path: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(server_default=text('now()'))
    expires_at: Mapped[datetime]
    consumed_at: Mapped[datetime | None]

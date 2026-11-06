"""Member-only group chat. Plain text is data, never a privileged command."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from trippilot.auth.deps import CurrentAccount, DbSession
from trippilot.realtime.events import append_trip_event
from trippilot.trips.models import TripMessage
from trippilot.trips.service import get_trip_view, lock_trip

router = APIRouter(prefix='/api/trips/{trip_id}/messages', tags=['chat'])
MESSAGE_CREATED = 'message.created'


class CreateMessage(BaseModel):
    """A client retains its UUID when retrying an ambiguous or failed send."""

    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)

    content: str = Field(min_length=1, max_length=4000)
    client_message_id: uuid.UUID


class MessageView(BaseModel):
    """A public message; no account-private profile or payment information."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    account_id: uuid.UUID
    client_message_id: uuid.UUID
    author_name: str
    content: str
    created_at: datetime


class MessageHistory(BaseModel):
    """Messages in display order; `older_cursor` fetches the preceding page."""

    messages: list[MessageView]
    older_cursor: int | None


@router.get('')
async def history(
    trip_id: uuid.UUID,
    account: CurrentAccount,
    db: DbSession,
    before: Annotated[int | None, Query(ge=1, le=9_223_372_036_854_775_807)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
) -> MessageHistory:
    """Read the latest messages or an older page, only as an active trip member."""
    await get_trip_view(db, trip_id, account)
    query = select(TripMessage).where(TripMessage.trip_id == trip_id)
    if before is not None:
        query = query.where(TripMessage.id < before)
    rows = list(await db.scalars(query.order_by(TripMessage.id.desc()).limit(limit + 1)))
    page = rows[:limit]
    return MessageHistory(
        messages=[MessageView.model_validate(row) for row in reversed(page)],
        older_cursor=page[-1].id if len(rows) > limit else None,
    )


@router.post('', status_code=status.HTTP_201_CREATED)
async def send_message(
    trip_id: uuid.UUID, body: CreateMessage, account: CurrentAccount, db: DbSession
) -> MessageView:
    """Save once and publish after commit; never trust a caller-supplied author."""
    await lock_trip(db, trip_id)
    await get_trip_view(db, trip_id, account)
    existing = await db.scalar(
        select(TripMessage).where(
            TripMessage.trip_id == trip_id,
            TripMessage.account_id == account.id,
            TripMessage.client_message_id == body.client_message_id,
        )
    )
    if existing is not None:
        if existing.content != body.content:
            raise HTTPException(
                status.HTTP_409_CONFLICT, 'Message ID already used for different text'
            )
        return MessageView.model_validate(existing)
    message = TripMessage(
        trip_id=trip_id,
        account_id=account.id,
        client_message_id=body.client_message_id,
        author_name=account.nickname or account.display_name,
        content=body.content,
    )
    db.add(message)
    await db.flush()
    await append_trip_event(db, trip_id, MESSAGE_CREATED, {'message_id': message.id})
    result = MessageView.model_validate(message)
    await db.commit()
    return result

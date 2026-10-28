"""The ledger is append-only: the database rejects UPDATE, DELETE and TRUNCATE."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from trippilot.payments.ledger import append_ledger_entry


async def _append(db: AsyncSession, actor_id: str, trip_id: uuid.UUID | None = None) -> int:
    entry_id = await append_ledger_entry(
        db,
        action='test.appended',
        actor_kind='script',
        actor_id=actor_id,
        trip_id=trip_id,
        request_id=f'req-{actor_id}',
        paypal_ids={'authorization_id': f'AUTH-{actor_id}'},
        amount_cents=125,
        detail={'note': 'unit'},
    )
    await db.commit()
    return entry_id


async def test_appending_returns_the_new_row_and_stores_every_field(db: AsyncSession) -> None:
    actor_id = uuid.uuid4().hex
    trip_id = uuid.uuid4()

    entry_id = await _append(db, actor_id, trip_id)

    row = (
        await db.execute(
            text(
                'SELECT action, actor_kind, actor_id, request_id, trip_id, paypal_ids, '
                'amount_cents, detail FROM ledger_entries WHERE id = :i'
            ),
            {'i': entry_id},
        )
    ).one()
    assert row.action == 'test.appended'
    assert row.actor_kind == 'script'
    assert row.trip_id == trip_id
    assert row.paypal_ids == {'authorization_id': f'AUTH-{actor_id}'}
    assert row.amount_cents == 125
    assert row.detail == {'note': 'unit'}


async def test_update_is_rejected_by_the_database(db: AsyncSession) -> None:
    actor_id = uuid.uuid4().hex
    entry_id = await _append(db, actor_id)

    with pytest.raises(DBAPIError, match='append-only'):
        await db.execute(
            text("UPDATE ledger_entries SET action = 'tampered' WHERE id = :i"), {'i': entry_id}
        )
    await db.rollback()

    action = (
        await db.execute(text('SELECT action FROM ledger_entries WHERE id = :i'), {'i': entry_id})
    ).scalar_one()
    assert action == 'test.appended'


async def test_delete_is_rejected_by_the_database(db: AsyncSession) -> None:
    actor_id = uuid.uuid4().hex
    entry_id = await _append(db, actor_id)

    with pytest.raises(DBAPIError, match='append-only'):
        await db.execute(text('DELETE FROM ledger_entries WHERE id = :i'), {'i': entry_id})
    await db.rollback()

    count = (
        await db.execute(text('SELECT count(*) FROM ledger_entries WHERE id = :i'), {'i': entry_id})
    ).scalar_one()
    assert count == 1


async def test_truncate_is_rejected_by_the_database(db: AsyncSession) -> None:
    actor_id = uuid.uuid4().hex
    entry_id = await _append(db, actor_id)

    with pytest.raises(DBAPIError, match='append-only'):
        await db.execute(text('TRUNCATE ledger_entries'))
    await db.rollback()

    count = (
        await db.execute(text('SELECT count(*) FROM ledger_entries WHERE id = :i'), {'i': entry_id})
    ).scalar_one()
    assert count == 1


async def test_trip_id_has_no_foreign_key_so_truncating_trips_never_reaches_the_ledger(
    db: AsyncSession,
) -> None:
    actor_id = uuid.uuid4().hex
    entry_id = await _append(db, actor_id, uuid.uuid4())

    constraints = (
        await db.execute(
            text(
                "SELECT count(*) FROM pg_constraint WHERE contype = 'f' "
                "AND 'ledger_entries'::regclass IN (conrelid, confrelid)"
            )
        )
    ).scalar_one()
    await db.execute(text('TRUNCATE trips RESTART IDENTITY CASCADE'))
    await db.commit()

    surviving = (
        await db.execute(text('SELECT count(*) FROM ledger_entries WHERE id = :i'), {'i': entry_id})
    ).scalar_one()
    assert constraints == 0
    assert surviving == 1


async def test_a_second_append_gets_a_later_id_than_the_first(db: AsyncSession) -> None:
    first = await _append(db, uuid.uuid4().hex)
    second = await _append(db, uuid.uuid4().hex)

    assert second > first

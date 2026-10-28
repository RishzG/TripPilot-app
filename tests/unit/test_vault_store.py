"""VaultStore: encrypted token storage, rotation, one active row per owner, ledgered use."""

from __future__ import annotations

import asyncio
import base64
import uuid
from collections.abc import Mapping
from typing import Any

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from trippilot.contracts.paypal import PaymentToken
from trippilot.db.engine import session_factory
from trippilot.payments.ledger import Actor
from trippilot.payments.vault_store import VaultError, VaultStore


def new_key() -> str:
    """Return a fresh Fernet key as text (tests never reuse or print real keys)."""
    return Fernet.generate_key().decode()


def make_token(label: str | None = None) -> PaymentToken:
    """Return a payment token whose ids are unique to the call."""
    tag = label or uuid.uuid4().hex
    return PaymentToken(
        id=f'PT-{tag}', customer_id=f'CUST-{tag}', payer_id=f'PAYER-{tag}', email='b@example.test'
    )


def actor_for(owner_id: uuid.UUID) -> Actor:
    """Return a member actor whose id is the owner (so ledger rows are filterable per test)."""
    return Actor(kind='member', id=str(owner_id))


async def ledger_rows(db: AsyncSession, **match: str) -> list[Mapping[str, Any]]:
    """Return ledger rows filtered by one test-unique column (`request_id` or `actor_id`)."""
    ((column, value),) = match.items()
    queries = {
        'request_id': text(
            'SELECT action, actor_kind, actor_id, request_id, trip_id, detail '
            'FROM ledger_entries WHERE request_id = :v ORDER BY id'
        ),
        'actor_id': text(
            'SELECT action, actor_kind, actor_id, request_id, trip_id, detail '
            'FROM ledger_entries WHERE actor_id = :v ORDER BY id'
        ),
    }
    result = await db.execute(queries[column], {'v': value})
    return [dict(row._mapping) for row in result]


async def active_rows(db: AsyncSession, owner_id: uuid.UUID) -> list[Mapping[str, Any]]:
    """Return the vault_tokens rows for an owner that are not soft-deleted."""
    result = await db.execute(
        text(
            'SELECT id, payer_id, token_ciphertext, key_version FROM vault_tokens '
            'WHERE owner_id = :o AND deleted_at IS NULL'
        ),
        {'o': owner_id},
    )
    return [dict(row._mapping) for row in result]


async def test_a_saved_token_round_trips_through_ciphertext(db: AsyncSession) -> None:
    store = VaultStore([new_key()])
    owner = uuid.uuid4()
    token = make_token()

    saved = await store.save(db, 'account', owner, token, actor_for(owner))
    await db.commit()
    used = await store.use_token(
        db,
        saved.vault_token_id,
        actor_kind='system',
        actor_id=str(owner),
        purpose='unit-test',
        request_id=f'req-{uuid.uuid4().hex}',
    )

    assert used == token.id
    assert saved.superseded_payment_token_id is None


async def test_ciphertext_contains_neither_the_token_id_nor_the_customer_id(
    db: AsyncSession,
) -> None:
    store = VaultStore([new_key()])
    owner = uuid.uuid4()
    token = make_token()

    await store.save(db, 'account', owner, token, actor_for(owner))
    await db.commit()

    (row,) = await active_rows(db, owner)
    ciphertext = bytes(row['token_ciphertext'])
    decoded_once = base64.urlsafe_b64decode(ciphertext)
    for needle in (token.id.encode(), (token.customer_id or '').encode()):
        assert needle not in ciphertext
        assert needle not in decoded_once
    # payer_id is a plain, non-secret column (it is never a way to use the token).
    assert row['payer_id'] == token.payer_id


async def test_rows_encrypted_under_an_old_key_still_decrypt_after_a_new_key_is_added(
    db: AsyncSession,
) -> None:
    old_key, new = new_key(), new_key()
    old_store = VaultStore([old_key])
    owner = uuid.uuid4()
    token = make_token()
    saved = await old_store.save(db, 'account', owner, token, actor_for(owner))
    await db.commit()

    rotated_store = VaultStore([new, old_key])
    used = await rotated_store.use_token(
        db,
        saved.vault_token_id,
        actor_kind='system',
        actor_id=str(owner),
        purpose='unit-test',
        request_id=f'req-{uuid.uuid4().hex}',
    )

    assert used == token.id


async def test_rotate_re_encrypts_rows_under_the_newest_key_and_updates_key_version(
    db: AsyncSession,
) -> None:
    old_key, new = new_key(), new_key()
    old_store = VaultStore([old_key])
    owner = uuid.uuid4()
    token = make_token()
    saved = await old_store.save(db, 'account', owner, token, actor_for(owner))
    await db.commit()
    (before,) = await active_rows(db, owner)

    rotated_store = VaultStore([new, old_key])
    count = await rotated_store.rotate(db)
    await db.commit()
    (after,) = await active_rows(db, owner)

    assert count >= 1
    assert before['key_version'] == old_store.key_version
    assert after['key_version'] == rotated_store.key_version
    assert after['key_version'] != before['key_version']
    assert bytes(after['token_ciphertext']) != bytes(before['token_ciphertext'])
    # After dropping the old key, only the new key remains and the row still decrypts.
    only_new = VaultStore([new])
    used = await only_new.use_token(
        db,
        saved.vault_token_id,
        actor_kind='system',
        actor_id=str(owner),
        purpose='unit-test',
        request_id=f'req-{uuid.uuid4().hex}',
    )
    assert used == token.id
    assert await rotated_store.rotate(db) == 0


async def test_save_supersedes_the_active_row_and_returns_the_old_token_id(
    db: AsyncSession,
) -> None:
    store = VaultStore([new_key()])
    owner = uuid.uuid4()
    first, second = make_token(), make_token()

    first_result = await store.save(db, 'account', owner, first, actor_for(owner))
    await db.commit()
    second_result = await store.save(db, 'account', owner, second, actor_for(owner))
    await db.commit()

    assert second_result.superseded_payment_token_id == first.id
    assert second_result.vault_token_id != first_result.vault_token_id
    (row,) = await active_rows(db, owner)
    assert row['id'] == second_result.vault_token_id


async def test_two_concurrent_saves_for_one_owner_leave_exactly_one_active_row(
    db: AsyncSession,
) -> None:
    store = VaultStore([new_key()])
    owner = uuid.uuid4()
    first, second = make_token(), make_token()

    async def save(token: PaymentToken) -> str | None:
        async with session_factory() as session:
            result = await store.save(session, 'account', owner, token, actor_for(owner))
            await session.commit()
            return result.superseded_payment_token_id

    superseded = await asyncio.gather(save(first), save(second))

    rows = await active_rows(db, owner)
    assert len(rows) == 1
    # Exactly one of the two saves found (and superseded) the other's token.
    assert sorted(s is not None for s in superseded) == [False, True]
    assert {s for s in superseded if s is not None} <= {first.id, second.id}


async def test_use_token_returns_the_id_and_writes_a_ledger_row_in_the_same_transaction(
    db: AsyncSession,
) -> None:
    store = VaultStore([new_key()])
    owner = uuid.uuid4()
    trip = uuid.uuid4()
    token = make_token()
    saved = await store.save(db, 'account', owner, token, actor_for(owner))
    await db.commit()
    request_id = f'req-{uuid.uuid4().hex}'

    used = await store.use_token(
        db,
        saved.vault_token_id,
        actor_kind='system',
        actor_id=str(owner),
        purpose='hold-test',
        request_id=request_id,
        trip_id=trip,
    )
    await db.commit()

    assert used == token.id
    (row,) = await ledger_rows(db, request_id=request_id)
    assert row['action'] == 'vault.token_used'
    assert row['actor_kind'] == 'system'
    assert row['trip_id'] == trip
    assert row['detail']['purpose'] == 'hold-test'
    assert token.id not in str(row) and (token.customer_id or '') not in str(row)


async def test_rolling_back_removes_both_the_ledger_row_and_the_last_used_stamp(
    db: AsyncSession,
) -> None:
    store = VaultStore([new_key()])
    owner = uuid.uuid4()
    saved = await store.save(db, 'account', owner, make_token(), actor_for(owner))
    await db.commit()
    request_id = f'req-{uuid.uuid4().hex}'

    await store.use_token(
        db,
        saved.vault_token_id,
        actor_kind='system',
        actor_id=str(owner),
        purpose='rollback-test',
        request_id=request_id,
    )
    await db.rollback()

    assert await ledger_rows(db, request_id=request_id) == []
    last_used = (
        await db.execute(
            text('SELECT last_used_at FROM vault_tokens WHERE id = :i'), {'i': saved.vault_token_id}
        )
    ).scalar_one()
    assert last_used is None


async def test_use_token_refuses_a_removed_or_unknown_token(db: AsyncSession) -> None:
    store = VaultStore([new_key()])
    owner = uuid.uuid4()
    saved = await store.save(db, 'account', owner, make_token(), actor_for(owner))
    await store.remove(db, 'account', owner, actor_for(owner))
    await db.commit()

    for vault_token_id in (saved.vault_token_id, uuid.uuid4()):
        with pytest.raises(VaultError):
            await store.use_token(
                db,
                vault_token_id,
                actor_kind='system',
                actor_id=str(owner),
                purpose='unit-test',
                request_id=f'req-{uuid.uuid4().hex}',
            )


async def test_status_and_remove_follow_the_active_row(db: AsyncSession) -> None:
    store = VaultStore([new_key()])
    owner = uuid.uuid4()
    token = make_token()

    assert await store.status(db, 'account', owner) is False
    assert await store.remove(db, 'account', owner, actor_for(owner)) is None
    await store.save(db, 'account', owner, token, actor_for(owner))
    await db.commit()
    assert await store.status(db, 'account', owner) is True
    removed = await store.remove(db, 'account', owner, actor_for(owner))
    await db.commit()

    assert removed == token.id
    assert await store.status(db, 'account', owner) is False
    assert await active_rows(db, owner) == []


async def test_save_and_remove_each_write_a_ledger_row_without_token_or_customer_ids(
    db: AsyncSession,
) -> None:
    store = VaultStore([new_key()])
    owner = uuid.uuid4()
    token = make_token()

    await store.save(db, 'account', owner, token, actor_for(owner))
    await store.remove(db, 'account', owner, actor_for(owner))
    await db.commit()

    rows = await ledger_rows(db, actor_id=str(owner))
    assert [r['action'] for r in rows] == ['vault.saved', 'vault.removed']
    assert rows[0]['detail']['payer_id'] == token.payer_id
    for row in rows:
        assert token.id not in str(row)
        assert (token.customer_id or '') not in str(row)


def test_a_store_without_keys_is_refused() -> None:
    with pytest.raises(VaultError):
        VaultStore([])

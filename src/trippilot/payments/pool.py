"""The simulated-friends buyer pool: enrolment bookkeeping and trip leases (D-12, D-13, D-17).

A pool buyer is a sandbox personal account whose saved PayPal was approved once, by a human, in the
environment that owns it (UD-1). This module keeps the buyer rows, links each to its vault token
and leases enrolled buyers to trips so one buyer is never held by two trips at once. It never
touches PayPal and never reads or returns a payment token id: the token lives in `vault_tokens`
(owner_kind `pool_buyer`, owner_id = the buyer's row id) and is used through `VaultStore.use_token`.

Leasing uses `FOR UPDATE SKIP LOCKED`, so concurrent trips take disjoint buyers without waiting on
each other. The partial unique index on `buyer_leases` stays the backstop: it makes a double lease
impossible even if this logic had a bug. The caller commits.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import exists, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from trippilot.payments.models import BuyerLease, PoolBuyer, VaultToken

POOL_OWNER_KIND = 'pool_buyer'
"""The `vault_tokens.owner_kind` of a pool buyer's saved PayPal."""

DEFAULT_LEASE_TTL = timedelta(hours=24)
LEASE_ROUNDS = 3
"""How many times `lease_buyers` re-selects when a locked candidate turns out to be taken."""


class PoolError(Exception):
    """A refusal the router turns into an HTTP status (404 `not_found`, 409 `slug_taken`, ...)."""

    def __init__(self, status_code: int, code: str) -> None:
        """Record the HTTP status and the short machine code."""
        self.status_code = status_code
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class LeasedBuyer:
    """A buyer leased to a trip. `vault_token_id` is our row id, never a PayPal token id."""

    lease_id: uuid.UUID
    pool_buyer_id: uuid.UUID
    slug: str
    persona_slug: str | None
    vault_token_id: uuid.UUID


async def add_pool_buyer(
    db: AsyncSession,
    slug: str,
    persona_slug: str | None,
    sandbox_email: str | None,
    environment: str,
) -> PoolBuyer:
    """Create a pending buyer row for `environment`.

    Raises:
        PoolError: 409 `slug_taken` when a buyer with this slug already exists.
    """
    buyer = PoolBuyer(
        slug=slug,
        persona_slug=persona_slug,
        sandbox_email=sandbox_email,
        environment=environment,
        status='pending',
    )
    try:
        async with db.begin_nested():
            db.add(buyer)
            await db.flush()
    except IntegrityError as error:
        raise PoolError(409, 'slug_taken') from error
    return buyer


async def list_pool(db: AsyncSession, environment: str) -> list[PoolBuyer]:
    """Return the environment's buyers, ordered by slug."""
    result = await db.scalars(
        select(PoolBuyer).where(PoolBuyer.environment == environment).order_by(PoolBuyer.slug)
    )
    return list(result)


async def get_pool_buyer(db: AsyncSession, slug: str, environment: str) -> PoolBuyer | None:
    """Return the environment's buyer with this slug, or None."""
    return await db.scalar(
        select(PoolBuyer).where(PoolBuyer.slug == slug, PoolBuyer.environment == environment)
    )


async def active_vault_token_id(db: AsyncSession, pool_buyer_id: uuid.UUID) -> uuid.UUID | None:
    """Return our row id of the buyer's active saved PayPal, or None when it has none."""
    return await db.scalar(
        select(VaultToken.id).where(
            VaultToken.owner_kind == POOL_OWNER_KIND,
            VaultToken.owner_id == pool_buyer_id,
            VaultToken.deleted_at.is_(None),
        )
    )


async def mark_enrolled(db: AsyncSession, slug: str, vault_token_id: uuid.UUID) -> None:
    """Link the buyer to its (new) vault token row and mark it enrolled.

    Raises:
        PoolError: 404 `not_found` when no buyer has this slug.
    """
    updated = await db.scalar(
        update(PoolBuyer)
        .where(PoolBuyer.slug == slug)
        .values(vault_token_id=vault_token_id, status='enrolled')
        .returning(PoolBuyer.id)
    )
    if updated is None:
        raise PoolError(404, 'not_found')


async def lease_buyers(
    db: AsyncSession,
    trip_id: uuid.UUID,
    n: int,
    ttl: timedelta = DEFAULT_LEASE_TTL,
    *,
    environment: str | None = None,
) -> list[LeasedBuyer]:
    """Lease up to `n` enrolled, unleased buyers to the trip; fewer come back when fewer are free.

    Expired leases are released first. Candidates are locked with `FOR UPDATE SKIP LOCKED`, so a
    concurrent call for another trip skips them and takes different buyers. The caller commits;
    until then the locks (and the new lease rows) are invisible to other transactions.
    """
    now = datetime.now(UTC)
    await db.execute(
        update(BuyerLease)
        .where(BuyerLease.released_at.is_(None), BuyerLease.expires_at <= now)
        .values(released_at=now)
    )
    open_lease = exists().where(
        BuyerLease.pool_buyer_id == PoolBuyer.id, BuyerLease.released_at.is_(None)
    )
    chosen: list[PoolBuyer] = []
    skipped: set[uuid.UUID] = set()
    for _ in range(LEASE_ROUNDS):
        need = n - len(chosen)
        if need <= 0:
            break
        query = (
            select(PoolBuyer)
            .where(
                PoolBuyer.status == 'enrolled',
                PoolBuyer.vault_token_id.is_not(None),
                ~open_lease,
                PoolBuyer.id.not_in({buyer.id for buyer in chosen} | skipped),
            )
            .order_by(PoolBuyer.slug)
            .limit(need)
            .with_for_update(skip_locked=True)
        )
        if environment is not None:
            query = query.where(PoolBuyer.environment == environment)
        candidates = list(await db.scalars(query))
        if not candidates:
            break
        # A lease committed after our statement began is invisible to the NOT EXISTS above but is
        # visible to this fresh statement, now that we hold the row locks.
        taken = set(
            await db.scalars(
                select(BuyerLease.pool_buyer_id).where(
                    BuyerLease.pool_buyer_id.in_([buyer.id for buyer in candidates]),
                    BuyerLease.released_at.is_(None),
                )
            )
        )
        for buyer in candidates:
            if buyer.id in taken:
                skipped.add(buyer.id)
            else:
                chosen.append(buyer)

    leases = [
        BuyerLease(pool_buyer_id=buyer.id, trip_id=trip_id, expires_at=now + ttl)
        for buyer in chosen
    ]
    db.add_all(leases)
    await db.flush()
    return [
        LeasedBuyer(
            lease_id=lease.id,
            pool_buyer_id=buyer.id,
            slug=buyer.slug,
            persona_slug=buyer.persona_slug,
            vault_token_id=_required_token(buyer),
        )
        for lease, buyer in zip(leases, chosen, strict=True)
    ]


def _required_token(buyer: PoolBuyer) -> uuid.UUID:
    """Return the buyer's vault token row id; the lease query guarantees it is set."""
    if buyer.vault_token_id is None:
        raise PoolError(409, 'not_enrolled')
    return buyer.vault_token_id


async def release_lease(db: AsyncSession, lease_id: uuid.UUID) -> None:
    """Release a lease so its buyer can be leased again; an unknown or released lease is a no-op."""
    await db.execute(
        update(BuyerLease)
        .where(BuyerLease.id == lease_id, BuyerLease.released_at.is_(None))
        .values(released_at=datetime.now(UTC))
    )

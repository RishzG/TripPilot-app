"""Three saved buyers, one run: $1.00 holds, one partial capture, two voids (plan 01-14, D-35, D-36).

ROADMAP criterion 4: place a hold on each of three enrolled pool buyers in one run, capture $0.50
of the first with ``final_capture`` and void the other two, so no hold stays open. Every call
writes a ledger row (the field contract of 01-13: ``paypal_ids.authorization_id``,
``detail.status``, ``detail.expiration_time``, ``amount_cents``) and the Sandbox checks page
shows them.

It is meant to run INSIDE Render as a one-off job, so settings come from the process environment
(``get_settings()``; there is no ``.env.staging`` loading): APP_ENV=staging, DATABASE_URL (the
private URL), VAULT_KEYS, PAYPAL_MODE=sandbox, PAYPAL_CLIENT_ID and PAYPAL_CLIENT_SECRET. From the
repo root of a deployed image::

    python scripts/spikes/three_buyer_holds.py --run-id oct29
    python scripts/spikes/three_buyer_holds.py --run-id oct29 --report

Safety:
- Refuses unless PAYPAL_MODE is ``sandbox``, the PayPal API host is a sandbox host and APP_ENV is
  not ``production``.
- Request ids are ``spike3-<run-id>-<slug>-hold|capture|void``. A step that already has its
  ledger row is skipped and PayPal also dedupes on the same request id, so re-running a run id
  never creates a second hold. After a failure, re-run the same run id to resume.
- It only ever touches the authorizations it creates itself; the two open 01-18 test holds are
  never read from arguments, and a guard refuses them by id.
- ``--report`` is read-only and calls neither PayPal nor anything that writes.
- Prints ids and statuses only. Never a token, key or secret.
"""

from __future__ import annotations

import argparse
import asyncio
import re
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import timedelta
from typing import Final
from uuid import UUID
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from trippilot.contracts.money import Cents
from trippilot.contracts.paypal import PayPalError, PayPalGateway
from trippilot.db.engine import configure_event_loop_policy, dispose_engine, get_engine
from trippilot.db.engine import session_factory as make_session
from trippilot.payments.ledger import append_ledger_entry
from trippilot.payments.models import LedgerEntry, PoolBuyer, WebhookEvent
from trippilot.payments.pool import list_pool
from trippilot.payments.vault_store import VaultError, VaultStore, parse_vault_keys
from trippilot.settings import Settings, get_settings

ACTOR_KIND: Final = 'script'
ACTOR_ID: Final = 'three_buyer_holds'
HOLD_CENTS: Final = Cents(100)
CAPTURE_CENTS: Final = Cents(50)
PREFERRED_ORDER: Final = ('maya', 'sam', 'ana')
"""The buyers used when all three are enrolled; the first one is captured, the others voided."""
BUYER_COUNT: Final = 3
RUN_ID_PATTERN: Final = re.compile(r'^[A-Za-z0-9][A-Za-z0-9-]{0,39}$')
PROTECTED_AUTHORIZATIONS: Final = frozenset({'3HJ189595J804324R', '21G42554211627257'})
"""The two open 01-18 reauthorization test holds. This script never touches them."""
EXPECTED_FINAL: Final = ('CAPTURED', 'VOIDED', 'VOIDED')
WEBHOOK_SLACK: Final = timedelta(minutes=1)


class SpikeError(Exception):
    """A run problem the operator can act on; the message never carries a secret."""


@dataclass
class BuyerRun:
    """One buyer's progress through the run, rebuilt from the ledger on every start."""

    slug: str
    vault_token_id: UUID
    authorization_id: str | None = None
    final_status: str | None = None


def request_id(run_id: str, slug: str, step: str) -> str:
    """Return the deterministic request id of one step, e.g. `spike3-oct29-maya-hold`."""
    return f'spike3-{run_id}-{slug}-{step}'


def refusal(settings: Settings) -> str | None:
    """Return why this run must not start, or None when it is a sandbox, non-production run."""
    if settings.paypal_mode != 'sandbox':
        return 'PAYPAL_MODE must be sandbox'
    host = (urlsplit(settings.paypal_api_base).hostname or '').lower()
    if host != 'sandbox.paypal.com' and not host.endswith('.sandbox.paypal.com'):
        return 'PAYPAL_API_BASE is not a sandbox host'
    if settings.app_env == 'production':
        return 'APP_ENV is production; this spike runs on staging'
    if not settings.paypal_client_id or not settings.paypal_client_secret.get_secret_value():
        return 'PAYPAL_CLIENT_ID and PAYPAL_CLIENT_SECRET are not set'
    return None


def _check_not_protected(authorization_id: str) -> None:
    """Refuse to act on one of the two open 01-18 holds."""
    if authorization_id in PROTECTED_AUTHORIZATIONS:
        raise SpikeError('refusing to touch an open 01-18 test hold')


def select_buyers(buyers: Sequence[PoolBuyer]) -> list[BuyerRun]:
    """Pick three enrolled buyers: maya, sam, ana when all are enrolled, else the first three."""
    enrolled = {
        b.slug: BuyerRun(slug=b.slug, vault_token_id=b.vault_token_id)
        for b in buyers
        if b.status == 'enrolled' and b.vault_token_id is not None
    }
    if all(slug in enrolled for slug in PREFERRED_ORDER):
        return [enrolled[slug] for slug in PREFERRED_ORDER]
    ordered = sorted(enrolled.values(), key=lambda buyer: buyer.slug)
    if len(ordered) < BUYER_COUNT:
        raise SpikeError(
            f'need {BUYER_COUNT} enrolled pool buyers for this environment, found {len(ordered)}'
        )
    return ordered[:BUYER_COUNT]


async def _ledger_row(db: AsyncSession, action: str, req_id: str) -> LedgerEntry | None:
    """Return this run's ledger row for an action and request id, or None."""
    return await db.scalar(
        select(LedgerEntry)
        .where(LedgerEntry.action == action, LedgerEntry.request_id == req_id)
        .order_by(LedgerEntry.id)
        .limit(1)
    )


def _ids(entry: LedgerEntry, key: str) -> str | None:
    """Return a string PayPal id from a ledger row's `paypal_ids`, or None."""
    value = entry.paypal_ids.get(key)
    return value if isinstance(value, str) else None


async def _place_hold(
    db: AsyncSession,
    store: VaultStore,
    gateway: PayPalGateway,
    run_id: str,
    buyer: BuyerRun,
) -> None:
    """Place the $1.00 hold for one buyer unless this run already ledgered it."""
    req_id = request_id(run_id, buyer.slug, 'hold')
    existing = await _ledger_row(db, 'hold.placed', req_id)
    if existing is not None:
        buyer.authorization_id = _ids(existing, 'authorization_id')
        print(f'{buyer.slug}: hold already placed {buyer.authorization_id} (skipped)')
        return
    payment_token_id = await store.use_token(
        db,
        buyer.vault_token_id,
        actor_kind=ACTOR_KIND,
        actor_id=ACTOR_ID,
        purpose='spike hold',
        request_id=req_id,
    )
    try:
        vaulted = await gateway.create_order_authorize_vaulted(
            request_id=req_id,
            payment_token_id=payment_token_id,
            amount=HOLD_CENTS,
            description=f'TripPilot spike hold {run_id}',
        )
    except PayPalError as error:
        await append_ledger_entry(
            db,
            action='hold.failed',
            actor_kind=ACTOR_KIND,
            actor_id=ACTOR_ID,
            request_id=req_id,
            amount_cents=HOLD_CENTS,
            detail={'buyer_slug': buyer.slug, 'run_id': run_id, 'paypal_error': error.summary()},
        )
        await db.commit()  # keep the attempt on the record
        raise
    _check_not_protected(vaulted.authorization_id)
    status = vaulted.status
    expiration: str | None = None
    try:
        live = await gateway.get_authorization(vaulted.authorization_id)
        status, expiration = live.status, live.expiration_time
    except PayPalError:
        pass  # the hold exists; the row records what the create call returned
    await append_ledger_entry(
        db,
        action='hold.placed',
        actor_kind=ACTOR_KIND,
        actor_id=ACTOR_ID,
        request_id=req_id,
        paypal_ids={'authorization_id': vaulted.authorization_id, 'order_id': vaulted.order_id},
        amount_cents=HOLD_CENTS,
        detail={
            'status': status,
            'expiration_time': expiration,
            'buyer_slug': buyer.slug,
            'run_id': run_id,
        },
    )
    await db.commit()
    buyer.authorization_id = vaulted.authorization_id
    print(f'{buyer.slug}: hold placed {vaulted.authorization_id} ({status})')


async def _live_state(gateway: PayPalGateway, authorization_id: str) -> tuple[str, str | None]:
    """Read an authorization's status and expiration from PayPal (read-only)."""
    live = await gateway.get_authorization(authorization_id)
    return live.status, live.expiration_time


async def _capture(db: AsyncSession, gateway: PayPalGateway, run_id: str, buyer: BuyerRun) -> None:
    """Capture $0.50 with final_capture (releasing the rest) unless this run already did."""
    assert buyer.authorization_id is not None
    _check_not_protected(buyer.authorization_id)
    req_id = request_id(run_id, buyer.slug, 'capture')
    if await _ledger_row(db, 'hold.captured', req_id) is not None:
        print(f'{buyer.slug}: capture already done (skipped)')
        return
    try:
        capture = await gateway.capture_authorization(
            request_id=req_id,
            authorization_id=buyer.authorization_id,
            amount=CAPTURE_CENTS,
            final_capture=True,
        )
    except PayPalError as error:
        await append_ledger_entry(
            db,
            action='hold.failed',
            actor_kind=ACTOR_KIND,
            actor_id=ACTOR_ID,
            request_id=req_id,
            paypal_ids={'authorization_id': buyer.authorization_id},
            amount_cents=CAPTURE_CENTS,
            detail={'buyer_slug': buyer.slug, 'run_id': run_id, 'paypal_error': error.summary()},
        )
        await db.commit()
        raise
    status, expiration = await _live_state(gateway, buyer.authorization_id)
    await append_ledger_entry(
        db,
        action='hold.captured',
        actor_kind=ACTOR_KIND,
        actor_id=ACTOR_ID,
        request_id=req_id,
        paypal_ids={'authorization_id': buyer.authorization_id, 'capture_id': capture.id},
        amount_cents=CAPTURE_CENTS,
        detail={
            'status': status,
            'expiration_time': expiration,
            'capture_status': capture.status,
            'final_capture': True,
            'released_cents': HOLD_CENTS - CAPTURE_CENTS,
            'buyer_slug': buyer.slug,
            'run_id': run_id,
        },
    )
    await db.commit()
    print(f'{buyer.slug}: captured {capture.id} ({status})')


async def _void(db: AsyncSession, gateway: PayPalGateway, run_id: str, buyer: BuyerRun) -> None:
    """Void the hold unless this run already did."""
    assert buyer.authorization_id is not None
    _check_not_protected(buyer.authorization_id)
    req_id = request_id(run_id, buyer.slug, 'void')
    if await _ledger_row(db, 'hold.voided', req_id) is not None:
        print(f'{buyer.slug}: void already done (skipped)')
        return
    try:
        voided = await gateway.void_authorization(
            request_id=req_id, authorization_id=buyer.authorization_id
        )
    except PayPalError as error:
        await append_ledger_entry(
            db,
            action='hold.failed',
            actor_kind=ACTOR_KIND,
            actor_id=ACTOR_ID,
            request_id=req_id,
            paypal_ids={'authorization_id': buyer.authorization_id},
            amount_cents=HOLD_CENTS,
            detail={'buyer_slug': buyer.slug, 'run_id': run_id, 'paypal_error': error.summary()},
        )
        await db.commit()
        raise
    await append_ledger_entry(
        db,
        action='hold.voided',
        actor_kind=ACTOR_KIND,
        actor_id=ACTOR_ID,
        request_id=req_id,
        paypal_ids={'authorization_id': buyer.authorization_id},
        amount_cents=HOLD_CENTS,
        detail={
            'status': voided.status,
            'expiration_time': voided.expiration_time,
            'buyer_slug': buyer.slug,
            'run_id': run_id,
        },
    )
    await db.commit()
    print(f'{buyer.slug}: voided {buyer.authorization_id} ({voided.status})')


async def run_spike(
    run_id: str, *, settings: Settings | None = None, gateway: PayPalGateway | None = None
) -> int:
    """Place, capture and void the three holds; return 0 only when the final statuses are right.

    Exit codes: 0 done, 1 a PayPal or run failure (re-run the same run id to resume), 2 refused.
    """
    cfg = settings or get_settings()
    problem = refusal(cfg)
    if problem is not None:
        print(f'refusing to run: {problem}', file=sys.stderr)
        return 2
    if gateway is None:
        from trippilot.payments import get_paypal_gateway

        gateway = get_paypal_gateway()
    try:
        store = VaultStore(parse_vault_keys(cfg.vault_keys.get_secret_value()))
    except VaultError as error:
        print(f'refusing to run: {error}', file=sys.stderr)
        return 2

    get_engine()
    async with make_session() as db:
        try:
            buyers = select_buyers(await list_pool(db, cfg.app_env))
        except SpikeError as error:
            print(f'refusing to run: {error}', file=sys.stderr)
            return 2
        print(f'run {run_id} on {cfg.app_env}: buyers {", ".join(b.slug for b in buyers)}')
        try:
            for buyer in buyers:
                await _place_hold(db, store, gateway, run_id, buyer)
            await _capture(db, gateway, run_id, buyers[0])
            for buyer in buyers[1:]:
                await _void(db, gateway, run_id, buyer)
            for buyer in buyers:
                assert buyer.authorization_id is not None
                buyer.final_status, _ = await _live_state(gateway, buyer.authorization_id)
        except (PayPalError, SpikeError) as error:
            detail = error.summary() if isinstance(error, PayPalError) else str(error)
            print(f'run stopped: {detail}', file=sys.stderr)
            print(
                f're-run with --run-id {run_id} to resume; nothing is duplicated', file=sys.stderr
            )
            return 1

    print('final statuses (read from PayPal):')
    for buyer in buyers:
        print(f'  {buyer.slug}  {buyer.authorization_id}  {buyer.final_status}')
    final = tuple(b.final_status for b in buyers)
    if final != EXPECTED_FINAL:
        print(f'unexpected final statuses {final}; expected {EXPECTED_FINAL}', file=sys.stderr)
        return 1
    print(f'done: wait about two minutes, then run with --run-id {run_id} --report')
    return 0


async def report(run_id: str) -> int:
    """Print this run's ledger rows and the webhook events received since it started (read-only)."""
    prefix = f'spike3-{run_id}-'
    get_engine()
    async with make_session() as db:
        rows = list(
            await db.scalars(
                select(LedgerEntry)
                .where(LedgerEntry.request_id.startswith(prefix, autoescape=True))
                .order_by(LedgerEntry.id)
            )
        )
        if not rows:
            print(f'no ledger rows for run {run_id}')
            return 1
        started = rows[0].occurred_at - WEBHOOK_SLACK
        events = list(
            await db.scalars(
                select(WebhookEvent)
                .where(WebhookEvent.received_at >= started)
                .order_by(WebhookEvent.received_at)
            )
        )

    print(f'ledger rows for run {run_id}:')
    final: dict[str, tuple[str, str]] = {}
    run_ids: set[str] = set()
    for row in rows:
        auth = _ids(row, 'authorization_id')
        status = row.detail.get('status')
        status_text = status if isinstance(status, str) else None
        slug = row.detail.get('buyer_slug')
        for key in ('authorization_id', 'capture_id', 'order_id'):
            found = _ids(row, key)
            if found:
                run_ids.add(found)
        if auth and status_text and row.action in ('hold.placed', 'hold.captured', 'hold.voided'):
            final[auth] = (str(slug), status_text)
        cents = f'{row.amount_cents}c' if row.amount_cents is not None else '-'
        print(
            f'  #{row.id} {row.occurred_at:%Y-%m-%d %H:%M:%S} {row.action:<18} '
            f'{row.request_id} {auth or "-"} {status_text or "-"} {cents}'
        )

    print('authorizations (final status from the ledger):')
    for auth, (slug, status) in final.items():
        print(f'  {slug}  {auth}  {status}')
    statuses = tuple(status for _, status in final.values())
    verdict = 'OK' if sorted(statuses) == sorted(EXPECTED_FINAL) else 'NOT FINAL'
    print(f'final statuses: {", ".join(statuses) or "none"} -> {verdict}')

    print(f'webhook events received since {started:%Y-%m-%d %H:%M:%S} UTC:')
    mine = 0
    for event in events:
        ours = event.resource_id in run_ids
        mine += 1 if ours and event.verification_status == 'SUCCESS' else 0
        print(
            f'  {"*" if ours else " "} {event.received_at:%H:%M:%S} {event.event_type} '
            f'{event.resource_id or "-"} verification={event.verification_status} '
            f'processed={"yes" if event.processed_at else "no"}'
        )
    if not events:
        print('  none')
    print(f"verified events on this run's authorizations or captures (*): {mine}")
    return 0 if verdict == 'OK' else 1


def main(argv: Sequence[str] | None = None) -> int:
    """Parse the command line and run or report."""
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0] if __doc__ else None)
    parser.add_argument('--run-id', required=True, help='letters, digits and dashes, e.g. oct29')
    parser.add_argument('--report', action='store_true', help='read-only: print the run and exit')
    args = parser.parse_args(argv)
    run_id = str(args.run_id)
    if not RUN_ID_PATTERN.fullmatch(run_id):
        print('--run-id must be letters, digits and dashes (at most 40)', file=sys.stderr)
        return 2
    configure_event_loop_policy()

    async def go() -> int:
        try:
            return await (report(run_id) if args.report else run_spike(run_id))
        finally:
            await dispose_engine()

    return asyncio.run(go())


if __name__ == '__main__':
    sys.exit(main())

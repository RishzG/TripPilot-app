"""Financial and scheduling invariants independent of providers or a database."""

import uuid
from datetime import date, time

import pytest
from pydantic import ValidationError

from trippilot.planning.domain import TripContext, shares, validate_schedule
from trippilot.planning.pilot import PilotError, budget_check
from trippilot.planning.sample import sample_plan


def test_shares_reconcile_and_are_stable_under_member_order() -> None:
    for cents in range(111):
        result = shares(cents, ['c', 'a', 'b'])
        assert result == shares(cents, ['b', 'c', 'a'])
        assert sum(result.values()) == cents
        assert max(result.values()) - min(result.values()) <= 1
    assert shares(100, ['c', 'a', 'b']) == {'a': 34, 'b': 33, 'c': 33}
    with pytest.raises(ValueError):
        shares(100, ['a', 'a'])


@pytest.mark.parametrize(
    'patch',
    [
        {'timezone': 'Not/AZone'},
        {'start_date': '2026-11-08'},
        {'start_date': '2026-11-08', 'end_date': '2026-11-07'},
    ],
)
def test_invalid_shared_context_is_rejected(patch: dict[str, str]) -> None:
    with pytest.raises(ValidationError):
        TripContext.model_validate(
            {'name': 'Trip', 'destination': 'Chicago', 'revision': 0, **patch}
        )


def test_overlap_and_dst_gap_do_not_become_a_scheduled_plan() -> None:
    day = date(2026, 3, 8)
    draft = sample_plan(day, [uuid.uuid4()])
    context = TripContext(
        name='Trip',
        destination='Chicago',
        start_date=day,
        end_date=day,
        timezone='America/Chicago',
        revision=0,
    )
    validate_schedule(draft, context)
    draft.items[1].starts_at = time(10, 30)
    with pytest.raises(ValueError, match='overlap'):
        validate_schedule(draft, context)
    draft.items[1].starts_at = time(2, 30)
    with pytest.raises(ValueError, match='DST'):
        validate_schedule(draft, context)


def test_exact_budget_ceiling_is_hard_and_error_has_no_private_values() -> None:
    member = uuid.uuid4()
    draft = sample_plan(date(2026, 11, 7), [member])
    budget_check(draft, [{'account_id': str(member), 'budget_cents': 3200}])
    with pytest.raises(PilotError) as error:
        budget_check(draft, [{'account_id': str(member), 'budget_cents': 3199}])
    assert '3199' not in str(error.value)
    assert str(member) not in str(error.value)

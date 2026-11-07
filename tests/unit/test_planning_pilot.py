"""Provider boundaries: no private research, per-member evaluation, no invented output."""

import json
import uuid
from datetime import date
from typing import Any

import httpx
import pytest
import respx
from pydantic import SecretStr

from trippilot.planning import pilot
from trippilot.planning.sample import sample_plan
from trippilot.settings import Settings


def response(value: object) -> dict[str, Any]:
    return {
        'status': 'completed',
        'output': [
            {'type': 'message', 'content': [{'type': 'output_text', 'text': json.dumps(value)}]}
        ],
    }


async def test_private_evaluation_is_isolated_and_only_intersects_public_candidate_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    members = [uuid.uuid4(), uuid.uuid4()]
    draft = sample_plan(date(2026, 11, 7), members)
    private: list[dict[str, Any]] = [
        {
            'account_id': str(member),
            'budget_cents': 0,
            'dietary_notes': f'secret-{index}',
            'concerns': [f'constraint-{index}'],
        }
        for index, member in enumerate(members)
    ]
    seen: list[str] = []

    async def request(
        settings: Settings, instructions: str, data: dict[str, Any], *, research: bool
    ) -> dict[str, Any]:
        assert not research
        assert len(data['members_private']) == 1
        member = data['members_private'][0]
        index = next(
            i for i, value in enumerate(private) if value['account_id'] == member['account_id']
        )
        assert f'secret-{1 - index}' not in json.dumps(data)
        seen.append(member['account_id'])
        return response(
            {
                'selected_item_ids': [str(draft.items[0].id)],
                'explanations': {member['account_id']: f'Your own secret-{index}'},
            }
        )

    monkeypatch.setattr(pilot, 'request', request)
    selected, notes = await pilot.assess_candidates(draft, private, Settings())
    assert set(seen) == {str(member) for member in members}
    assert selected.items == [draft.items[0]]
    assert 'secret-1' not in notes[str(members[0])]
    assert 'secret-0' not in notes[str(members[1])]


async def test_constraint_conflict_never_becomes_a_successful_draft(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    member = uuid.uuid4()
    draft = sample_plan(date(2026, 11, 7), [member])

    async def request(
        settings: Settings, instructions: str, data: dict[str, Any], *, research: bool
    ) -> dict[str, Any]:
        return response(
            {'selected_item_ids': [], 'explanations': {str(member): 'Cannot satisfy allergy'}}
        )

    monkeypatch.setattr(pilot, 'request', request)
    with pytest.raises(pilot.PilotError, match='constraints'):
        await pilot.assess_candidates(
            draft, [{'account_id': str(member), 'budget_cents': None}], Settings()
        )


async def test_research_rejects_unsubstantiated_sources(monkeypatch: pytest.MonkeyPatch) -> None:
    member = uuid.uuid4()
    draft = sample_plan(date(2026, 11, 7), [member])

    async def request(
        settings: Settings, instructions: str, data: dict[str, Any], *, research: bool
    ) -> dict[str, Any]:
        return response(draft.model_dump(mode='json'))

    monkeypatch.setattr(pilot, 'request', request)
    public = {
        'members': [{'account_id': str(member)}],
        'trip': {'start_date': '2026-11-07', 'end_date': '2026-11-07'},
    }
    with pytest.raises(pilot.PilotError, match='substantiate'):
        await pilot.research(public, Settings())


@respx.mock
@pytest.mark.parametrize('status', [400, 401, 402, 429, 503])
async def test_provider_errors_are_safe_and_not_retried(status: int) -> None:
    route = respx.post('https://ai-gateway.vercel.sh/v1/responses').mock(
        return_value=httpx.Response(status, json={'private': 'private-prompt-echo'})
    )
    settings = Settings(ai_gateway_api_key=SecretStr('test'), pilot_model='test/model')
    with pytest.raises(pilot.PilotError) as error:
        await pilot.request(settings, 'internal instruction', {'private': 'secret'}, research=False)
    assert 'private-prompt-echo' not in str(error.value)
    assert route.call_count == 1

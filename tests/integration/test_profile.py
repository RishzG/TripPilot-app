"""Profile API (plan 01-15, ACC-03 and ACC-04): PATCH /api/me and what other members can see."""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path
from typing import TYPE_CHECKING

import httpx
import psycopg
import pytest
from cryptography.fernet import Fernet
from fastapi import FastAPI
from pydantic import SecretStr

from trippilot.app import create_app
from trippilot.payments import get_paypal_gateway
from trippilot.payments.fake import FakePayPal
from trippilot.settings import get_settings
from trippilot.trips.invites import invite_rate_limit

if TYPE_CHECKING:
    from conftest import MakeClient, MakeMember, PersonaClient

Conn = psycopg.Connection[tuple[object, ...]]

REPO_ROOT = Path(__file__).resolve().parents[2]
AVATAR_DIR = REPO_ROOT / 'web' / 'src' / 'assets' / 'avatars'
EXPECTED_KEYS = [
    'maya',
    'sam',
    'ana',
    'leo',
    'priya',
    'jules',
    'kai',
    'noor',
    'tess',
    'omar',
    'ivy',
    'ravi',
    'zoe',
    'finn',
    'lena',
    'theo',
]


def _cookie(raw: str) -> dict[str, str]:
    """Return a Cookie header carrying the raw session value."""
    return {'Cookie': f'tp_session={raw}'}


async def _no_limit() -> None:
    """Stand-in for the per-IP invite limiter."""


@pytest.fixture
def fake() -> FakePayPal:
    """Return the fake PayPal every request in a test talks to."""
    return FakePayPal()


@pytest.fixture
def app(fake: FakePayPal) -> Iterator[FastAPI]:
    """Return a non-demo app with FakePayPal and a fresh vault key."""
    settings = get_settings().model_copy(
        update={
            'demo_mode': False,
            'paypal_mode': 'fake',
            'paypal_client_id': 'test-client-id-not-a-secret',
            'vault_keys': SecretStr(Fernet.generate_key().decode()),
        }
    )
    built = create_app(settings)
    built.dependency_overrides[get_paypal_gateway] = lambda: fake
    built.dependency_overrides[invite_rate_limit] = _no_limit
    yield built


async def _me(http: httpx.AsyncClient, raw: str) -> dict[str, object]:
    """Return GET /api/me for the session."""
    response = await http.get('/api/me', headers=_cookie(raw))
    assert response.status_code == 200, response.text
    body: dict[str, object] = response.json()
    return body


async def test_patch_nickname_stores_it_trimmed_and_me_reflects_it(
    app: FastAPI, make_client: MakeClient, make_member: MakeMember
) -> None:
    _, raw = await make_member('Samantha Jones')
    http = make_client(app)

    response = await http.patch('/api/me', json={'nickname': '  Sammy  '}, headers=_cookie(raw))

    assert response.status_code == 200, response.text
    assert response.json()['nickname'] == 'Sammy'
    assert (await _me(http, raw))['nickname'] == 'Sammy'


@pytest.mark.parametrize('nickname', ['', '   ', 'x' * 41])
async def test_patch_rejects_an_empty_or_too_long_nickname(
    app: FastAPI, make_client: MakeClient, make_member: MakeMember, nickname: str
) -> None:
    _, raw = await make_member('Samantha Jones')
    http = make_client(app)

    response = await http.patch('/api/me', json={'nickname': nickname}, headers=_cookie(raw))

    assert response.status_code == 422
    assert (await _me(http, raw))['nickname'] is None


async def test_patch_accepts_a_forty_character_nickname(
    app: FastAPI, make_client: MakeClient, make_member: MakeMember
) -> None:
    _, raw = await make_member('Samantha Jones')
    http = make_client(app)

    response = await http.patch('/api/me', json={'nickname': 'x' * 40}, headers=_cookie(raw))

    assert response.status_code == 200, response.text
    assert response.json()['nickname'] == 'x' * 40


async def test_patch_stores_an_allowed_illustrated_avatar(
    app: FastAPI, make_client: MakeClient, make_member: MakeMember
) -> None:
    _, raw = await make_member('Samantha Jones')
    http = make_client(app)

    response = await http.patch(
        '/api/me',
        json={'avatar_kind': 'illustrated', 'avatar_key': 'theo'},
        headers=_cookie(raw),
    )

    assert response.status_code == 200, response.text
    me = await _me(http, raw)
    assert me['avatar_kind'] == 'illustrated'
    assert me['avatar_key'] == 'theo'


@pytest.mark.parametrize(
    'body',
    [
        {'avatar_kind': 'illustrated', 'avatar_key': 'not-in-the-set'},
        {'avatar_kind': 'illustrated', 'avatar_key': '../../etc/passwd'},
        {'avatar_kind': 'illustrated'},
        {'avatar_kind': 'photo', 'avatar_key': 'maya'},
        {'avatar_key': 'maya'},
        {},
    ],
)
async def test_patch_rejects_an_unknown_or_incomplete_avatar(
    app: FastAPI, make_client: MakeClient, make_member: MakeMember, body: dict[str, str]
) -> None:
    _, raw = await make_member('Samantha Jones')
    http = make_client(app)

    response = await http.patch('/api/me', json=body, headers=_cookie(raw))

    assert response.status_code == 422
    me = await _me(http, raw)
    assert me['avatar_kind'] == 'initials'
    assert me['avatar_key'] is None


async def test_patch_to_initials_clears_the_avatar_key(
    app: FastAPI, make_client: MakeClient, make_member: MakeMember
) -> None:
    _, raw = await make_member('Samantha Jones')
    http = make_client(app)
    await http.patch(
        '/api/me', json={'avatar_kind': 'illustrated', 'avatar_key': 'kai'}, headers=_cookie(raw)
    )

    response = await http.patch('/api/me', json={'avatar_kind': 'initials'}, headers=_cookie(raw))

    assert response.status_code == 200, response.text
    me = await _me(http, raw)
    assert me['avatar_kind'] == 'initials'
    assert me['avatar_key'] is None


async def test_patch_changes_nickname_and_avatar_together_and_only_for_the_caller(
    app: FastAPI, make_client: MakeClient, make_member: MakeMember
) -> None:
    _, raw = await make_member('Samantha Jones')
    _, other_raw = await make_member('Other Person')
    http = make_client(app)

    response = await http.patch(
        '/api/me',
        json={'nickname': 'Sammy', 'avatar_kind': 'illustrated', 'avatar_key': 'ivy'},
        headers=_cookie(raw),
    )

    assert response.status_code == 200, response.text
    other = await _me(http, other_raw)
    assert other['nickname'] is None
    assert other['avatar_key'] is None


async def test_patch_needs_a_signed_in_member(app: FastAPI, make_client: MakeClient) -> None:
    http = make_client(app)

    response = await http.patch('/api/me', json={'nickname': 'Sammy'})

    assert response.status_code == 401


async def test_patch_from_a_foreign_origin_is_refused(
    app: FastAPI, make_client: MakeClient, make_member: MakeMember
) -> None:
    _, raw = await make_member('Samantha Jones')
    http = make_client(app)

    foreign = await http.patch(
        '/api/me',
        json={'nickname': 'Sammy'},
        headers={**_cookie(raw), 'Origin': 'https://evil.example'},
    )
    own = await http.patch(
        '/api/me',
        json={'nickname': 'Sammy'},
        headers={**_cookie(raw), 'Origin': app.state.settings.public_base_url.rstrip('/')},
    )

    assert foreign.status_code == 403
    assert own.status_code == 200, own.text


async def test_a_demo_persona_cannot_edit_the_shared_persona_profile(
    persona_client: PersonaClient, sync_conn: Conn
) -> None:
    http = await persona_client('maya')
    before = sync_conn.execute(
        "SELECT nickname, avatar_kind, avatar_key FROM accounts WHERE display_name = 'Maya'"
    ).fetchall()

    response = await http.patch('/api/me', json={'nickname': 'Hacked'})

    assert response.status_code == 403
    after = sync_conn.execute(
        "SELECT nickname, avatar_kind, avatar_key FROM accounts WHERE display_name = 'Maya'"
    ).fetchall()
    assert after == before


async def test_trip_member_entries_show_names_and_avatars_but_never_saved_paypal(
    app: FastAPI,
    make_client: MakeClient,
    make_member: MakeMember,
    fake: FakePayPal,
) -> None:
    _, organiser_raw = await make_member('Olivia Organiser')
    _, friend_raw = await make_member('Fred Friend')
    http = make_client(app)
    await http.patch(
        '/api/me',
        json={'nickname': 'Freddy', 'avatar_kind': 'illustrated', 'avatar_key': 'omar'},
        headers=_cookie(friend_raw),
    )
    created = await http.post('/api/trips', json={'name': 'Tahoe'}, headers=_cookie(organiser_raw))
    trip_id = created.json()['id']
    invite = await http.get(f'/api/trips/{trip_id}/invite', headers=_cookie(organiser_raw))
    token = invite.json()['url'].rsplit('/join/', 1)[1]
    joined = await http.post(f'/api/invites/{token}/join', headers=_cookie(friend_raw))
    assert joined.status_code == 200, joined.text
    setup = await http.post('/api/paypal/vault/setup-token', headers=_cookie(friend_raw))
    saved = await http.post(
        '/api/paypal/vault/payment-token',
        json={'vaultSetupToken': setup.json()['vaultSetupToken']},
        headers=_cookie(friend_raw),
    )
    assert saved.json() == {'saved': True}

    as_organiser = await http.get(f'/api/trips/{trip_id}', headers=_cookie(organiser_raw))
    as_friend = await http.get(f'/api/trips/{trip_id}', headers=_cookie(friend_raw))

    for view in (as_organiser, as_friend):
        assert view.status_code == 200, view.text
        members = view.json()['members']
        assert len(members) == 2
        for member in members:
            assert set(member) == {
                'account_id',
                'display_name',
                'nickname',
                'avatar_kind',
                'avatar_key',
                'role',
            }
        by_name = {m['display_name']: m for m in members}
        assert by_name['Fred Friend']['nickname'] == 'Freddy'
        assert by_name['Fred Friend']['avatar_key'] == 'omar'
        assert by_name['Olivia Organiser']['avatar_kind'] == 'initials'
        for secret in ('saved', 'vault', 'paypal', *(t.id for t in fake.payment_tokens.values())):
            assert secret not in view.text.lower()


def test_the_allowed_avatar_keys_match_the_ui_spec_set_and_the_bundled_files() -> None:
    from trippilot.auth.avatars import ILLUSTRATED_AVATAR_KEYS
    from trippilot.demo.cast import CAST

    index = (AVATAR_DIR / 'index.ts').read_text(encoding='utf-8')
    block = re.search(r'AVATAR_KEYS = \[(.*?)\] as const', index, re.DOTALL)
    assert block is not None
    in_index = re.findall(r"'([a-z]+)'", block.group(1))

    assert in_index == EXPECTED_KEYS
    assert frozenset(EXPECTED_KEYS) == ILLUSTRATED_AVATAR_KEYS
    assert [persona.avatar_key for persona in CAST] == EXPECTED_KEYS[:6]
    for key in EXPECTED_KEYS:
        assert (AVATAR_DIR / f'{key}.svg').is_file()
    licence = (AVATAR_DIR / 'LICENSE.md').read_text(encoding='utf-8')
    assert 'CC0 1.0' in licence
    assert 'CC0 1.0' in index

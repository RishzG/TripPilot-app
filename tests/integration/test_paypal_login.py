"""Log in with PayPal start and callback (plan 01-12, ACC-02), against FakePayPal only."""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from typing import TYPE_CHECKING, Any
from urllib.parse import parse_qs, urlsplit

import httpx
import psycopg
import pytest
from fastapi import FastAPI

from trippilot.app import create_app
from trippilot.payments import get_paypal_gateway
from trippilot.payments.fake import FakePayPal
from trippilot.settings import get_settings
from trippilot.trips.invites import invite_rate_limit

if TYPE_CHECKING:
    from conftest import MakeClient, MakeMember

Conn = psycopg.Connection[tuple[object, ...]]

CLIENT_ID = 'test-client-id-not-a-secret'
REDIRECT_URI = 'http://localhost:8000/api/auth/paypal/callback'
SUB = 'PP-SUB-JO-0001'
OAUTH_COOKIE = 'tp_oauth'
SESSION_COOKIE = 'tp_session'


def claims(
    sub: str = SUB, name: str = 'Jo Joiner', email: str = 'jo@example.test'
) -> dict[str, Any]:
    """Return userinfo claims in the shape the 01-10 spike recorded (no given_name)."""
    return {
        'sub': sub,
        'user_id': sub,
        'name': name,
        'emails': [{'value': email, 'primary': True, 'confirmed': True}],
    }


async def _no_limit() -> None:
    """Stand-in for the per-IP invite limiter."""


@pytest.fixture
def fake() -> FakePayPal:
    """Return the fake PayPal every request in a test talks to."""
    return FakePayPal()


@pytest.fixture
def app(fake: FakePayPal) -> Iterator[FastAPI]:
    """Return a non-demo local app wired to the fake gateway with a login redirect URI."""
    settings = get_settings().model_copy(
        update={
            'demo_mode': False,
            'app_env': 'local',
            'paypal_mode': 'fake',
            'paypal_client_id': CLIENT_ID,
            'paypal_web_base': 'https://www.sandbox.paypal.com',
            'paypal_login_redirect_uri': REDIRECT_URI,
            'public_base_url': 'http://localhost:8000',
        }
    )
    built = create_app(settings)
    built.dependency_overrides[get_paypal_gateway] = lambda: fake
    built.dependency_overrides[invite_rate_limit] = _no_limit
    yield built


def _cookie(**cookies: str) -> dict[str, str]:
    """Return a Cookie header carrying exactly the given cookies."""
    return {'Cookie': '; '.join(f'{name}={value}' for name, value in cookies.items())}


def _set_cookies(response: httpx.Response) -> dict[str, str]:
    """Return each Set-Cookie header of a response keyed by cookie name (the whole header line)."""
    lines = response.headers.get_list('set-cookie')
    return {line.split('=', 1)[0]: line for line in lines}


def _cookie_value(line: str) -> str:
    """Return the value part of a Set-Cookie line."""
    return line.split(';', 1)[0].split('=', 1)[1]


def _scalar(conn: Conn, query: str, params: tuple[Any, ...] = ()) -> Any:
    """Return the first column of the first row of a query."""
    row = conn.execute(query, params).fetchone()
    assert row is not None
    return row[0]


async def _trip_with_invite(
    http: httpx.AsyncClient, make_member: MakeMember
) -> tuple[str, str, str]:
    """Start a trip as an organiser; return (trip_id, raw invite token, organiser cookie)."""
    _, organiser_raw = await make_member('Olivia Organiser')
    started = await http.post(
        '/api/trips', json={'name': 'Tahoe weekend'}, headers=_cookie(tp_session=organiser_raw)
    )
    assert started.status_code == 201, started.text
    trip_id = str(started.json()['id'])
    invite = await http.get(
        f'/api/trips/{trip_id}/invite', headers=_cookie(tp_session=organiser_raw)
    )
    token = str(invite.json()['url']).rsplit('/join/', 1)[1]
    return trip_id, token, organiser_raw


async def _start(http: httpx.AsyncClient, **params: str) -> tuple[httpx.Response, str]:
    """GET the start route; return the response and the state PayPal would echo back."""
    response = await http.get('/api/auth/paypal/start', params=params)
    assert response.status_code == 302, response.text
    query = parse_qs(urlsplit(response.headers['location']).query)
    return response, query['state'][0]


async def _callback(
    http: httpx.AsyncClient,
    state: str,
    *,
    code: str = 'code-1',
    cookie_state: str | None = None,
    session_raw: str | None = None,
) -> httpx.Response:
    """GET the callback the way the browser returns from PayPal, with explicit cookies."""
    cookies: dict[str, str] = {}
    if cookie_state is not None:
        cookies[OAUTH_COOKIE] = cookie_state
    if session_raw is not None:
        cookies[SESSION_COOKIE] = session_raw
    return await http.get(
        '/api/auth/paypal/callback',
        params={'code': code, 'state': state},
        headers=_cookie(**cookies),
    )


async def _login_with_invite(
    http: httpx.AsyncClient,
    fake: FakePayPal,
    token: str | None,
    *,
    code: str = 'code-1',
    user: dict[str, Any] | None = None,
    session_raw: str | None = None,
) -> httpx.Response:
    """Run start then callback for one sign-in and return the callback response."""
    fake.register_login(code, user if user is not None else claims())
    params = {'invite': token} if token is not None else {}
    _, state = await _start(http, **params)
    return await _callback(http, state, code=code, cookie_state=state, session_raw=session_raw)


def _session_count(conn: Conn) -> int:
    """Return the number of session rows."""
    return int(_scalar(conn, 'SELECT count(*) FROM sessions'))


def _exchanges(fake: FakePayPal) -> list[dict[str, object]]:
    """Return the arguments of every login-code exchange the fake saw."""
    return [args for name, args in fake.calls if name == 'exchange_login_code']


async def test_start_redirects_to_paypal_with_a_state_and_a_httponly_cookie(
    app: FastAPI, make_client: MakeClient, make_member: MakeMember, sync_conn: Conn
) -> None:
    http = make_client(app)
    _, token, _ = await _trip_with_invite(http, make_member)

    response, state = await _start(http, invite=token, next='/trips/new')

    location = urlsplit(response.headers['location'])
    query = parse_qs(location.query)
    assert f'{location.scheme}://{location.netloc}{location.path}' == (
        'https://www.sandbox.paypal.com/connect'
    )
    assert query['client_id'] == [CLIENT_ID]
    assert query['response_type'] == ['code']
    assert 'openid' in query['scope'][0].split()
    assert query['redirect_uri'] == [REDIRECT_URI]
    cookie_line = _set_cookies(response)[OAUTH_COOKIE]
    assert _cookie_value(cookie_line) == state
    lowered = cookie_line.lower()
    assert 'httponly' in lowered
    assert 'path=/api/auth' in lowered
    assert 'max-age=600' in lowered
    assert 'samesite=lax' in lowered
    rows = sync_conn.execute('SELECT state_hash, invite_id, next_path FROM oauth_states').fetchall()
    assert len(rows) == 1
    state_hash, invite_id, next_path = rows[0]
    assert state_hash == hashlib.sha256(state.encode()).digest()
    assert invite_id is not None
    assert next_path == '/trips/new'
    whole_row = str(_scalar(sync_conn, 'SELECT oauth_states::text FROM oauth_states'))
    assert token not in whole_row
    assert state not in whole_row


async def test_start_with_an_unknown_invite_sends_the_visitor_to_the_bad_link_page(
    app: FastAPI, make_client: MakeClient, sync_conn: Conn
) -> None:
    http = make_client(app)

    response = await http.get('/api/auth/paypal/start', params={'invite': 'not-a-real-token'})

    assert response.status_code == 302
    assert response.headers['location'] == '/join-failed?reason=not_found'
    assert OAUTH_COOKIE not in _set_cookies(response)
    assert _scalar(sync_conn, 'SELECT count(*) FROM oauth_states') == 0


async def test_a_login_with_a_valid_invite_signs_in_joins_and_lands_on_welcome(
    app: FastAPI,
    fake: FakePayPal,
    make_client: MakeClient,
    make_member: MakeMember,
    sync_conn: Conn,
) -> None:
    http = make_client(app)
    trip_id, token, _ = await _trip_with_invite(http, make_member)

    response = await _login_with_invite(http, fake, token)

    assert response.status_code == 302
    assert response.headers['location'] == f'/welcome/{trip_id}'
    cookies = _set_cookies(response)
    session_line = cookies[SESSION_COOKIE]
    assert 'httponly' in session_line.lower()
    assert 'max-age=0' in cookies[OAUTH_COOKIE].lower()
    accounts = sync_conn.execute(
        'SELECT id, email, display_name, kind FROM accounts WHERE paypal_subject = %s', (SUB,)
    ).fetchall()
    assert len(accounts) == 1
    account_id, email, display_name, kind = accounts[0]
    assert (email, display_name, kind) == ('jo@example.test', 'Jo', 'member')
    status = _scalar(
        sync_conn,
        'SELECT status FROM members WHERE trip_id = %s AND account_id = %s',
        (trip_id, account_id),
    )
    assert status == 'active'
    me = await http.get('/api/me', headers=_cookie(tp_session=_cookie_value(session_line)))
    assert me.status_code == 200
    assert me.json()['is_persona'] is False
    assert _exchanges(fake)[0]['redirect_uri'] == REDIRECT_URI


async def test_given_name_wins_over_the_first_token_of_name(
    app: FastAPI,
    fake: FakePayPal,
    make_client: MakeClient,
    make_member: MakeMember,
    sync_conn: Conn,
) -> None:
    http = make_client(app)
    _, token, _ = await _trip_with_invite(http, make_member)

    await _login_with_invite(http, fake, token, user={**claims(), 'given_name': 'Joanna'})

    stored = _scalar(
        sync_conn, 'SELECT display_name FROM accounts WHERE paypal_subject = %s', (SUB,)
    )
    assert stored == 'Joanna'


async def test_login_always_issues_a_new_session_and_drops_the_old_one(
    app: FastAPI,
    fake: FakePayPal,
    make_client: MakeClient,
    make_member: MakeMember,
    sync_conn: Conn,
) -> None:
    http = make_client(app)
    _, token, _ = await _trip_with_invite(http, make_member)
    old_account, old_raw = await make_member('Previous Persona')

    response = await _login_with_invite(http, fake, token, session_raw=old_raw)

    new_raw = _cookie_value(_set_cookies(response)[SESSION_COOKIE])
    assert new_raw != old_raw
    old_rows = _scalar(
        sync_conn, 'SELECT count(*) FROM sessions WHERE account_id = %s', (old_account.id,)
    )
    assert old_rows == 0
    stale = await http.get('/api/me', headers=_cookie(tp_session=old_raw))
    assert stale.status_code == 401


async def test_a_reused_state_is_refused_and_creates_no_second_session(
    app: FastAPI,
    fake: FakePayPal,
    make_client: MakeClient,
    make_member: MakeMember,
    sync_conn: Conn,
) -> None:
    http = make_client(app)
    _, token, _ = await _trip_with_invite(http, make_member)
    fake.register_login('code-1', claims())
    _, state = await _start(http, invite=token)
    first = await _callback(http, state, code='code-1', cookie_state=state)
    sessions_after_first = _session_count(sync_conn)
    fake.register_login('code-2', claims())

    second = await _callback(http, state, code='code-2', cookie_state=state)

    assert first.status_code == 302
    assert second.status_code == 400
    assert SESSION_COOKIE not in _set_cookies(second)
    assert _session_count(sync_conn) == sessions_after_first


async def test_an_expired_state_is_refused(
    app: FastAPI,
    fake: FakePayPal,
    make_client: MakeClient,
    make_member: MakeMember,
    sync_conn: Conn,
) -> None:
    http = make_client(app)
    _, token, _ = await _trip_with_invite(http, make_member)
    fake.register_login('code-1', claims())
    _, state = await _start(http, invite=token)
    sync_conn.execute("UPDATE oauth_states SET expires_at = now() - interval '1 minute'")

    response = await _callback(http, state, cookie_state=state)

    assert response.status_code == 400
    assert SESSION_COOKIE not in _set_cookies(response)
    count = _scalar(sync_conn, 'SELECT count(*) FROM accounts WHERE paypal_subject = %s', (SUB,))
    assert count == 0
    assert _exchanges(fake) == []


async def test_a_state_that_differs_from_the_cookie_is_refused(
    app: FastAPI,
    fake: FakePayPal,
    make_client: MakeClient,
    make_member: MakeMember,
    sync_conn: Conn,
) -> None:
    http = make_client(app)
    _, token, _ = await _trip_with_invite(http, make_member)
    fake.register_login('code-1', claims())
    _, state_a = await _start(http, invite=token)
    _, state_b = await _start(http, invite=token)

    response = await _callback(http, state_a, cookie_state=state_b)

    assert response.status_code == 400
    assert _session_count(sync_conn) == 1  # only the organiser's
    assert _exchanges(fake) == []


async def test_a_missing_cookie_or_an_unknown_state_is_refused(
    app: FastAPI,
    fake: FakePayPal,
    make_client: MakeClient,
    make_member: MakeMember,
    sync_conn: Conn,
) -> None:
    http = make_client(app)
    _, token, _ = await _trip_with_invite(http, make_member)
    fake.register_login('code-1', claims())
    _, state = await _start(http, invite=token)

    no_cookie = await _callback(http, state)
    unknown = await _callback(http, 'never-issued', cookie_state='never-issued')

    assert no_cookie.status_code == 400
    assert unknown.status_code == 400
    assert _session_count(sync_conn) == 1
    still_valid = await _callback(http, state, cookie_state=state)
    assert still_valid.status_code == 302


@pytest.mark.parametrize(
    'hostile', ['https://evil.example', '//evil.example', '/\\evil.example', 'javascript:alert(1)']
)
async def test_a_next_path_that_is_not_a_same_origin_path_becomes_the_home_page(
    app: FastAPI, fake: FakePayPal, make_client: MakeClient, hostile: str
) -> None:
    http = make_client(app)
    fake.register_login('code-1', claims())
    _, state = await _start(http, next=hostile)

    response = await _callback(http, state, cookie_state=state)

    assert response.status_code == 302
    assert response.headers['location'] == '/'


async def test_a_plain_next_path_is_kept_when_there_is_no_invite(
    app: FastAPI, fake: FakePayPal, make_client: MakeClient
) -> None:
    http = make_client(app)
    fake.register_login('code-1', claims())
    _, state = await _start(http, next='/trips/new?from=signin')

    response = await _callback(http, state, cookie_state=state)

    assert response.headers['location'] == '/trips/new?from=signin'


async def test_a_full_trip_redirects_to_join_failed_but_still_signs_the_user_in(
    app: FastAPI,
    fake: FakePayPal,
    make_client: MakeClient,
    make_member: MakeMember,
    sync_conn: Conn,
) -> None:
    http = make_client(app)
    trip_id, token, _ = await _trip_with_invite(http, make_member)
    for index in range(11):
        _, raw = await make_member(f'Friend {index}')
        joined = await http.post(f'/api/invites/{token}/join', headers=_cookie(tp_session=raw))
        assert joined.status_code == 200

    response = await _login_with_invite(http, fake, token)

    assert response.headers['location'] == '/join-failed?reason=full'
    session_line = _set_cookies(response)[SESSION_COOKIE]
    me = await http.get('/api/me', headers=_cookie(tp_session=_cookie_value(session_line)))
    assert me.status_code == 200
    active = _scalar(
        sync_conn,
        "SELECT count(*) FROM members WHERE trip_id = %s AND status = 'active'",
        (trip_id,),
    )
    assert active == 12


async def test_a_closed_trip_redirects_to_join_failed_closed(
    app: FastAPI,
    fake: FakePayPal,
    make_client: MakeClient,
    make_member: MakeMember,
    sync_conn: Conn,
) -> None:
    http = make_client(app)
    trip_id, token, _ = await _trip_with_invite(http, make_member)
    sync_conn.execute('UPDATE trips SET joining_closed = true WHERE id = %s', (trip_id,))

    response = await _login_with_invite(http, fake, token)

    assert response.headers['location'] == '/join-failed?reason=closed'
    assert SESSION_COOKIE in _set_cookies(response)


async def test_a_removed_member_is_signed_in_but_not_rejoined(
    app: FastAPI,
    fake: FakePayPal,
    make_client: MakeClient,
    make_member: MakeMember,
    sync_conn: Conn,
) -> None:
    http = make_client(app)
    trip_id, token, _ = await _trip_with_invite(http, make_member)
    await _login_with_invite(http, fake, token, code='code-1')
    account_id = _scalar(sync_conn, 'SELECT id FROM accounts WHERE paypal_subject = %s', (SUB,))
    sync_conn.execute(
        "UPDATE members SET status = 'removed' WHERE trip_id = %s AND account_id = %s",
        (trip_id, account_id),
    )

    response = await _login_with_invite(http, fake, token, code='code-2')

    assert response.headers['location'] == '/join-failed?reason=removed'
    assert SESSION_COOKIE in _set_cookies(response)
    status = _scalar(
        sync_conn,
        'SELECT status FROM members WHERE trip_id = %s AND account_id = %s',
        (trip_id, account_id),
    )
    assert status == 'removed'


async def test_an_invite_reset_between_start_and_callback_is_a_bad_link_but_signs_in(
    app: FastAPI, fake: FakePayPal, make_client: MakeClient, make_member: MakeMember
) -> None:
    http = make_client(app)
    trip_id, token, organiser_raw = await _trip_with_invite(http, make_member)
    fake.register_login('code-1', claims())
    _, state = await _start(http, invite=token)
    reset = await http.post(
        f'/api/trips/{trip_id}/invite/reset', headers=_cookie(tp_session=organiser_raw)
    )
    assert reset.status_code == 200

    response = await _callback(http, state, cookie_state=state)

    assert response.headers['location'] == '/join-failed?reason=not_found'
    assert SESSION_COOKIE in _set_cookies(response)


async def test_a_second_login_with_the_same_subject_reuses_the_account_and_welcomes_again(
    app: FastAPI,
    fake: FakePayPal,
    make_client: MakeClient,
    make_member: MakeMember,
    sync_conn: Conn,
) -> None:
    http = make_client(app)
    trip_id, token, _ = await _trip_with_invite(http, make_member)
    await _login_with_invite(http, fake, token, code='code-1')

    again = await _login_with_invite(
        http, fake, token, code='code-2', user=claims(name='Someone Else', email='new@example.test')
    )

    assert again.headers['location'] == f'/welcome/{trip_id}'
    rows = sync_conn.execute(
        'SELECT email, display_name FROM accounts WHERE paypal_subject = %s', (SUB,)
    ).fetchall()
    assert rows == [('new@example.test', 'Jo')]


async def test_accounts_are_keyed_on_the_subject_never_on_the_email(
    app: FastAPI,
    fake: FakePayPal,
    make_client: MakeClient,
    make_member: MakeMember,
    sync_conn: Conn,
) -> None:
    http = make_client(app)
    _, token, _ = await _trip_with_invite(http, make_member)
    await _login_with_invite(http, fake, token, code='code-1', user=claims(sub='SUB-A'))

    await _login_with_invite(http, fake, token, code='code-2', user=claims(sub='SUB-B'))

    rows = sync_conn.execute(
        'SELECT paypal_subject, email FROM accounts WHERE paypal_subject IN (%s, %s) '
        'ORDER BY paypal_subject',
        ('SUB-A', 'SUB-B'),
    ).fetchall()
    assert rows == [('SUB-A', 'jo@example.test'), ('SUB-B', 'jo@example.test')]


async def test_a_cancelled_login_goes_back_to_sign_in_without_a_session(
    app: FastAPI, make_client: MakeClient, sync_conn: Conn
) -> None:
    http = make_client(app)
    _, state = await _start(http)

    response = await http.get(
        '/api/auth/paypal/callback',
        params={'error': 'access_denied', 'state': state},
        headers=_cookie(tp_oauth=state),
    )

    assert response.status_code == 302
    assert response.headers['location'] == '/signin?error=cancelled'
    assert SESSION_COOKIE not in _set_cookies(response)
    assert _session_count(sync_conn) == 0


async def test_a_paypal_failure_after_the_state_check_goes_back_to_sign_in(
    app: FastAPI, fake: FakePayPal, make_client: MakeClient, sync_conn: Conn
) -> None:
    http = make_client(app)
    _, state = await _start(http)

    unregistered = await _callback(http, state, code='never-registered', cookie_state=state)

    assert unregistered.status_code == 302
    assert unregistered.headers['location'] == '/signin?error=failed'
    assert SESSION_COOKIE not in _set_cookies(unregistered)
    fake.register_login('code-2', {'name': 'Nobody', 'emails': []})
    _, second_state = await _start(http)
    missing = await _callback(http, second_state, code='code-2', cookie_state=second_state)
    assert missing.headers['location'] == '/signin?error=failed'
    assert _session_count(sync_conn) == 0


def test_sanitize_next_path_only_lets_same_origin_relative_paths_through() -> None:
    from trippilot.auth.paypal_login import sanitize_next_path

    assert sanitize_next_path(None) == '/'
    assert sanitize_next_path('') == '/'
    assert sanitize_next_path('/trips/abc?x=1#top') == '/trips/abc?x=1#top'
    assert sanitize_next_path('//evil.example') == '/'
    assert sanitize_next_path('/\\evil.example') == '/'
    assert sanitize_next_path('https://evil.example/') == '/'
    assert sanitize_next_path('/ok\r\nSet-Cookie: x=1') == '/'
    assert sanitize_next_path('/' + 'a' * 3000) == '/'

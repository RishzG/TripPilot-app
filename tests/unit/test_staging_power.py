"""Unit tests for scripts/ops/staging_power.py (01-07): the staging suspend/resume tool.

The Render API and the staging health endpoint are mocked with respx, and the subprocess runner
(`gh` and the persistence smoke script) is a recording fake, so nothing here touches a network,
GitHub or a real process. Time is a fake clock, so the bounded polls finish instantly.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from collections.abc import Iterator, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Any

import httpx
import pytest
import respx

SCRIPT = Path(__file__).resolve().parents[2] / 'scripts' / 'ops' / 'staging_power.py'
SMOKE_NAME = 'hosted_persistence.py'

RENDER = 'https://api.render.com/v1'
BASE_URL = 'https://staging.example.test'
HEALTH_URL = f'{BASE_URL}/api/health'
API_KEY = 'test-render-key'
REPO = 'RishzG/TripPilot-app'
ENV = {
    'RENDER_API_KEY': API_KEY,
    'STAGING_BASE_URL': BASE_URL,
    'STAGING_WEB_SERVICE_ID': 'srv-web',
    'STAGING_WORKER_SERVICE_ID': 'srv-worker',
    'STAGING_DB_ID': 'dpg-db',
}

WEB_RESUME = ('http', 'POST', f'{RENDER}/services/srv-web/resume')
WORKER_RESUME = ('http', 'POST', f'{RENDER}/services/srv-worker/resume')
DB_RESUME = ('http', 'POST', f'{RENDER}/postgres/dpg-db/resume')
WEB_SUSPEND = ('http', 'POST', f'{RENDER}/services/srv-web/suspend')
WORKER_SUSPEND = ('http', 'POST', f'{RENDER}/services/srv-worker/suspend')
DB_SUSPEND = ('http', 'POST', f'{RENDER}/postgres/dpg-db/suspend')
WEB_RESTART = ('http', 'POST', f'{RENDER}/services/srv-web/restart')
WORKER_RESTART = ('http', 'POST', f'{RENDER}/services/srv-worker/restart')
HEALTH_GET = ('http', 'GET', HEALTH_URL)
NOW = datetime(2026, 10, 29, 12, 0, 0, tzinfo=UTC)
OWNER_ID = 'tea-owner1'

GH_ACTIVE_TRUE = (
    'run',
    'gh',
    'variable',
    'set',
    'STAGING_ACTIVE',
    '--body',
    'true',
    '--repo',
    REPO,
)
GH_ACTIVE_FALSE = (
    'run',
    'gh',
    'variable',
    'set',
    'STAGING_ACTIVE',
    '--body',
    'false',
    '--repo',
    REPO,
)
GH_RELEASE = ('run', 'gh', 'workflow', 'run', 'release.yml', '--ref', 'main', '--repo', REPO)


def health(started_at: str, worker_age: float | None) -> dict[str, object]:
    """Return a /api/health body as the app serves it."""
    return {
        'status': 'ok',
        'git_sha': 'abc123',
        'db': 'ok',
        'worker_last_seen_seconds': worker_age,
        'paypal_vault_scope': True,
        'started_at': started_at,
    }


class World:
    """Records every HTTP call and subprocess in order and owns the fake clock."""

    def __init__(self) -> None:
        self.events: list[tuple[str, ...]] = []
        self.render_auth: list[str | None] = []
        self.health_auth: list[str | None] = []
        self.sleeps: list[float] = []
        self.now = 0.0
        self.health_script: list[object] = [health('A', 3.0)]
        self.status_bodies: dict[str, str] = {}
        self.render_status = 202
        self.create_rc = 0
        self.check_rc = 0
        self.env_vars: dict[str, list[dict[str, Any]]] = {}
        self.env_put_status = 200
        self.env_puts: list[tuple[str, str, object]] = []
        self.env_get_queries: list[dict[str, str]] = []
        self.log_pages: list[dict[str, Any]] = []
        self.log_queries: list[dict[str, str]] = []
        self.logs_status = 200
        self.job_create_status = 201
        self.job_posts: list[tuple[str, object]] = []
        self.job_statuses: list[str] = ['running', 'succeeded']
        self.job_polls: list[str] = []
        self.job_cancels: list[str] = []
        self.service_owner: str | None = OWNER_ID

    def monotonic(self) -> float:
        """Fake monotonic clock."""
        return self.now

    def sleep(self, seconds: float) -> None:
        """Advance the fake clock instead of waiting."""
        self.sleeps.append(seconds)
        self.now += seconds

    def run(self, argv: Sequence[str]) -> subprocess.CompletedProcess[str]:
        """Record a subprocess call and answer it like `gh` or the smoke script."""
        self.events.append(('run', *argv))
        if len(argv) > 1 and str(argv[1]).endswith(SMOKE_NAME):
            checking = '--check' in argv
            code = self.check_rc if checking else self.create_rc
            out = '' if checking or code else 'trip-123\n'
            return subprocess.CompletedProcess(list(argv), code, stdout=out, stderr='')
        return subprocess.CompletedProcess(list(argv), 0, stdout='', stderr='')

    def _env_vars_response(self, request: httpx.Request) -> httpx.Response | None:
        """Answer the service env-var endpoints (list with cursor paging, and PUT one key)."""
        parts = request.url.path.strip('/').split('/')
        if len(parts) >= 4 and parts[1] == 'services' and parts[3] == 'env-vars':
            service_id = parts[2]
            if request.method == 'GET' and len(parts) == 4:
                query = dict(request.url.params)
                self.env_get_queries.append(query)
                items = self.env_vars.get(service_id, [])
                start = 0
                cursor = query.get('cursor')
                if cursor is not None:
                    cursors = [item.get('cursor') for item in items]
                    start = cursors.index(cursor) + 1
                limit = int(query.get('limit', '20'))
                return httpx.Response(200, json=items[start : start + limit])
            if request.method == 'PUT' and len(parts) == 5:
                body = json.loads(request.content)
                self.env_puts.append((service_id, parts[4], body))
                return httpx.Response(
                    self.env_put_status, json={'key': parts[4], 'value': body.get('value')}
                )
        return None

    def _logs_and_jobs_response(self, request: httpx.Request) -> httpx.Response | None:
        """Answer GET /logs, POST /services/{id}/jobs, GET .../jobs/{id} and the cancel call."""
        parts = request.url.path.strip('/').split('/')
        if parts == ['v1', 'logs'] and request.method == 'GET':
            self.log_queries.append(dict(request.url.params))
            if self.logs_status != 200:
                return httpx.Response(self.logs_status, json={})
            page = (
                self.log_pages.pop(0)
                if len(self.log_pages) > 1
                else (self.log_pages[0] if self.log_pages else {})
            )
            page_body: dict[str, Any] = {
                'hasMore': False,
                'nextStartTime': NOW.isoformat(),
                'nextEndTime': NOW.isoformat(),
            }
            page_body.update({'logs': []})
            page_body.update(page)
            return httpx.Response(200, json=page_body)
        if len(parts) >= 4 and parts[1] == 'services' and parts[3] == 'jobs':
            service_id = parts[2]
            if request.method == 'POST' and len(parts) == 4:
                self.job_posts.append((service_id, json.loads(request.content)))
                if self.job_create_status >= 400:
                    return httpx.Response(self.job_create_status, json={})
                return httpx.Response(
                    self.job_create_status,
                    json={
                        'id': 'job-123',
                        'serviceId': service_id,
                        'startCommand': 'x',
                        'planId': 'plan-srv-004',
                        'createdAt': '2026-10-29T08:00:05.000000-04:00',
                    },
                )
            if request.method == 'GET' and len(parts) == 5:
                self.job_polls.append(parts[4])
                state = (
                    self.job_statuses.pop(0) if len(self.job_statuses) > 1 else self.job_statuses[0]
                )
                body: dict[str, Any] = {
                    'id': parts[4],
                    'serviceId': service_id,
                    'status': state,
                    'createdAt': '2026-10-29T08:00:05.000000-04:00',
                }
                if state in ('succeeded', 'failed', 'canceled'):
                    body['startedAt'] = '2026-10-29T08:00:10.000000-04:00'
                    body['finishedAt'] = '2026-10-29T08:00:40.000000-04:00'
                return httpx.Response(200, json=body)
            if request.method == 'POST' and len(parts) == 6 and parts[5] == 'cancel':
                self.job_cancels.append(parts[4])
                return httpx.Response(200, json={})
        return None

    def _render_response(self, request: httpx.Request) -> httpx.Response:
        self.render_auth.append(request.headers.get('authorization'))
        env_response = self._env_vars_response(request)
        if env_response is not None:
            return env_response
        job_response = self._logs_and_jobs_response(request)
        if job_response is not None:
            return job_response
        self.events.append(('http', request.method, str(request.url)))
        if request.method == 'GET':
            state = self.status_bodies.get(str(request.url), 'not_suspended')
            body: dict[str, Any] = {'id': 'x', 'suspended': state}
            if self.service_owner is not None:
                body['ownerId'] = self.service_owner
            return httpx.Response(200, json=body)
        return httpx.Response(self.render_status, json={})

    def _health_response(self, request: httpx.Request) -> httpx.Response:
        self.events.append(('http', request.method, str(request.url)))
        self.health_auth.append(request.headers.get('authorization'))
        step = self.health_script.pop(0) if len(self.health_script) > 1 else self.health_script[0]
        if isinstance(step, Exception):
            raise step
        if isinstance(step, int):
            return httpx.Response(step, json={})
        return httpx.Response(200, json=step)

    def install(self, router: respx.MockRouter) -> None:
        """Route the Render API and the staging health URL to this world."""
        router.route(url__startswith=RENDER).mock(side_effect=self._render_response)
        router.route(url=HEALTH_URL).mock(side_effect=self._health_response)


@pytest.fixture(scope='session')
def sp() -> ModuleType:
    """Load scripts/ops/staging_power.py by path (scripts/ is not a package)."""
    spec = importlib.util.spec_from_file_location('staging_power', SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules['staging_power'] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def world() -> Iterator[tuple[World, respx.MockRouter]]:
    """A fresh world with the Render API and health routes mocked."""
    world = World()
    with respx.mock(assert_all_called=False) as router:
        world.install(router)
        yield world, router


def run_main(sp: Any, w: World, argv: Sequence[str], env: Mapping[str, str] | None = None) -> int:
    """Run `main` with the world's runner and clock."""
    code: int = sp.main(
        list(argv),
        env=dict(ENV if env is None else env),
        runner=w.run,
        sleep=w.sleep,
        monotonic=w.monotonic,
    )
    return code


World_ = tuple[World, respx.MockRouter]


def test_resume_brings_up_postgres_web_worker_then_waits_for_health_then_releases(
    sp: Any, world: World_
) -> None:
    """Resume order is Postgres, web, worker; then a bounded health poll; then the gh calls."""
    w, _router = world
    w.health_script = [503, httpx.ConnectError('down'), health('A', None), health('A', 2.0)]

    assert run_main(sp, w, ['resume']) == 0

    assert w.events == [
        DB_RESUME,
        WEB_RESUME,
        WORKER_RESUME,
        HEALTH_GET,
        HEALTH_GET,
        HEALTH_GET,
        GH_ACTIVE_TRUE,
        GH_RELEASE,
    ]
    assert w.sleeps
    assert all(seconds > 0 for seconds in w.sleeps)


def test_resume_never_marks_staging_active_when_health_does_not_come_up(
    sp: Any, world: World_
) -> None:
    """If /api/health is not ok before the timeout, resume fails and runs no gh command."""
    w, _router = world
    w.health_script = [503]

    code = run_main(sp, w, ['resume', '--timeout', '30'])

    assert code != 0
    assert not [event for event in w.events if event[0] == 'run']
    assert w.now <= 30 + 15


def test_suspend_clears_the_gate_first_then_suspends_worker_web_and_postgres(
    sp: Any, world: World_
) -> None:
    """STAGING_ACTIVE=false is set before any service is suspended."""
    w, _router = world

    assert run_main(sp, w, ['suspend']) == 0

    assert w.events == [GH_ACTIVE_FALSE, WORKER_SUSPEND, WEB_SUSPEND, DB_SUSPEND]


def test_status_prints_active_only_when_all_three_are_not_suspended(
    sp: Any, world: World_, capsys: pytest.CaptureFixture[str]
) -> None:
    """One suspended resource means staging is not active."""
    w, _router = world

    assert run_main(sp, w, ['status']) == 0
    assert 'staging: active' in capsys.readouterr().out

    w.status_bodies[f'{RENDER}/postgres/dpg-db'] = 'suspended'
    assert run_main(sp, w, ['status']) == 0
    out = capsys.readouterr().out
    assert 'staging: active' not in out
    assert 'database: suspended' in out
    assert 'web: active' in out
    assert 'worker: active' in out


def test_restart_proof_passes_once_the_process_restarted_and_the_worker_is_fresh(
    sp: Any, world: World_
) -> None:
    """Create trip, restart web and worker, wait for a new started_at and a fresh worker, check."""
    w, _router = world
    w.health_script = [
        health('A', 3.0),
        httpx.ConnectError('restarting'),
        502,
        health('A', 4.0),
        health('B', 70.0),
        health('B', 5.0),
    ]

    code = run_main(sp, w, ['restart-proof', '--timeout', '120'])

    assert code == 0
    smoke_create = [e for e in w.events if e[0] == 'run' and e[1] == sys.executable]
    assert len(smoke_create) == 2
    assert smoke_create[0][2].endswith(SMOKE_NAME)
    assert smoke_create[0][3:] == (BASE_URL,)
    assert smoke_create[1][3:] == (BASE_URL, '--check', 'trip-123')
    restarts = [e for e in w.events if e[1] == 'POST']
    assert restarts == [WEB_RESTART, WORKER_RESTART]
    assert w.events.index(smoke_create[0]) < w.events.index(WEB_RESTART)
    assert w.events.index(WORKER_RESTART) < w.events.index(smoke_create[1])
    assert 5.0 in w.sleeps


def test_restart_proof_fails_when_started_at_never_changes(sp: Any, world: World_) -> None:
    """A process that never restarted fails the proof and skips the final read-back."""
    w, _router = world
    w.health_script = [health('A', 3.0)]

    code = run_main(sp, w, ['restart-proof', '--timeout', '40'])

    assert code != 0
    assert not [e for e in w.events if e[0] == 'run' and '--check' in e]


def test_restart_proof_fails_when_the_worker_heartbeat_stays_stale(sp: Any, world: World_) -> None:
    """A new started_at with a worker heartbeat of 60 seconds or more is not enough."""
    w, _router = world
    w.health_script = [health('A', 3.0), health('B', 61.0)]

    code = run_main(sp, w, ['restart-proof', '--timeout', '40'])

    assert code != 0
    assert not [e for e in w.events if e[0] == 'run' and '--check' in e]


def test_restart_proof_fails_when_the_worker_heartbeat_is_missing(sp: Any, world: World_) -> None:
    """A null worker heartbeat (no worker running) fails the proof."""
    w, _router = world
    w.health_script = [health('A', 3.0), health('B', None)]

    assert run_main(sp, w, ['restart-proof', '--timeout', '40']) != 0


def test_restart_proof_stops_before_restarting_when_the_trip_cannot_be_created(
    sp: Any, world: World_
) -> None:
    """A failed smoke create means no restart is issued."""
    w, _router = world
    w.create_rc = 1

    code = run_main(sp, w, ['restart-proof', '--timeout', '40'])

    assert code != 0
    assert WEB_RESTART not in w.events
    assert WORKER_RESTART not in w.events


def test_restart_proof_fails_when_the_trip_is_gone_after_the_restart(
    sp: Any, world: World_
) -> None:
    """The read-back (`--check`) failing makes the whole proof fail."""
    w, _router = world
    w.health_script = [health('A', 3.0), health('B', 5.0)]
    w.check_rc = 1

    assert run_main(sp, w, ['restart-proof', '--timeout', '40']) != 0


def test_the_render_key_goes_only_to_render_and_is_never_printed(
    sp: Any, world: World_, capsys: pytest.CaptureFixture[str]
) -> None:
    """Bearer auth on Render calls only; the key appears in no output of any subcommand."""
    w, _router = world
    w.health_script = [health('A', 3.0), health('B', 5.0)]

    for argv in (['status'], ['resume'], ['suspend'], ['restart-proof', '--timeout', '40']):
        run_main(sp, w, argv)

    captured = capsys.readouterr()
    assert API_KEY not in captured.out
    assert API_KEY not in captured.err
    assert w.render_auth
    assert set(w.render_auth) == {f'Bearer {API_KEY}'}
    assert set(w.health_auth) == {None}
    assert not [e for e in w.events if e[0] == 'run' and any(API_KEY in part for part in e)]


def test_a_render_api_error_fails_with_the_status_and_never_the_key(
    sp: Any, world: World_, capsys: pytest.CaptureFixture[str]
) -> None:
    """A 401 from Render ends the command non-zero and reports only the status code."""
    w, _router = world
    w.render_status = 401

    code = run_main(sp, w, ['suspend'])

    assert code != 0
    captured = capsys.readouterr()
    assert '401' in captured.err
    assert API_KEY not in captured.out + captured.err


def test_gh_calls_name_the_repo_and_honour_the_gh_repo_override(sp: Any, world: World_) -> None:
    """Every gh argv carries --repo: the module default, or GH_REPO when set."""
    w, _router = world
    assert sp.GH_REPO_DEFAULT == REPO
    run_main(sp, w, ['suspend'])
    assert w.events[0] == GH_ACTIVE_FALSE

    w.events.clear()
    run_main(sp, w, ['suspend'], env={**ENV, 'GH_REPO': 'someone/else'})
    assert w.events[0][-2:] == ('--repo', 'someone/else')


def test_missing_environment_variables_are_named_without_values(
    sp: Any, world: World_, capsys: pytest.CaptureFixture[str]
) -> None:
    """Missing configuration exits 2 and lists variable names only."""
    w, _router = world
    env = {k: v for k, v in ENV.items() if k not in ('STAGING_DB_ID', 'RENDER_API_KEY')}

    code = run_main(sp, w, ['status'], env=env)

    assert code == 2
    err = capsys.readouterr().err
    assert 'STAGING_DB_ID' in err
    assert 'RENDER_API_KEY' in err
    assert BASE_URL not in err
    assert w.events == []


def test_the_env_file_is_parsed_like_a_dotenv_file(sp: Any, tmp_path: Path) -> None:
    """Comments, blanks, `export`, quotes and a Notepad BOM are handled; values stay verbatim."""
    env_file = tmp_path / 'staging.env'
    env_file.write_text(
        '\ufeff# staging power settings\n'
        '\n'
        'RENDER_API_KEY=rnd_abc=def\n'
        'export STAGING_BASE_URL="https://staging.example.test"\n'
        "STAGING_DB_ID='dpg-db'\n"
        '  STAGING_WEB_SERVICE_ID = srv-web  \n'
        'not a setting\n',
        encoding='utf-8',
    )

    assert sp.load_env_file(env_file) == {
        'RENDER_API_KEY': 'rnd_abc=def',
        'STAGING_BASE_URL': 'https://staging.example.test',
        'STAGING_DB_ID': 'dpg-db',
        'STAGING_WEB_SERVICE_ID': 'srv-web',
    }


def test_a_missing_env_file_is_an_empty_mapping(sp: Any, tmp_path: Path) -> None:
    """No file means no values, not an error (the environment may already hold them)."""
    assert sp.load_env_file(tmp_path / 'absent.env') == {}


def test_main_reads_the_env_file_and_the_process_environment_wins(
    sp: Any, world: World_, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without an explicit env, main loads STAGING_ENV_FILE and lets real variables override it."""
    w, _router = world
    env_file = tmp_path / 'staging.env'
    lines = [f'{key}={value}' for key, value in ENV.items() if key != 'STAGING_DB_ID']
    env_file.write_text('\n'.join([*lines, 'STAGING_DB_ID=dpg-from-file']) + '\n', encoding='utf-8')
    for key in ENV:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv('STAGING_ENV_FILE', str(env_file))
    monkeypatch.setenv('STAGING_DB_ID', 'dpg-db')

    code = sp.main(['status'], runner=w.run, sleep=w.sleep, monotonic=w.monotonic)

    assert code == 0
    assert ('http', 'GET', f'{RENDER}/postgres/dpg-db') in w.events
    assert w.render_auth[0] == f'Bearer {API_KEY}'


def _nested(key: str, value: str, cursor: str) -> dict[str, Any]:
    """One list item in the documented Render shape: {"envVar": {...}, "cursor": ...}."""
    return {'envVar': {'key': key, 'value': value}, 'cursor': cursor}


def test_env_keys_prints_only_the_sorted_key_names_of_each_service(
    sp: Any, world: World_, capsys: pytest.CaptureFixture[str]
) -> None:
    """Both Render list shapes are understood; keys are sorted and no value is ever printed."""
    w, _router = world
    w.env_vars['srv-web'] = [
        _nested('ZED', 'secret-zed-value', 'c1'),
        _nested('ALPHA', 'v-a', 'c2'),
    ]
    w.env_vars['srv-worker'] = [
        {'key': 'MIDDLE', 'value': 'secret-mid-value'},
        {'key': 'BETA', 'value': 'b'},
    ]

    assert run_main(sp, w, ['env-keys']) == 0

    out = capsys.readouterr()
    assert out.out.splitlines() == ['web: ALPHA, ZED', 'worker: BETA, MIDDLE']
    assert 'secret-zed-value' not in out.out + out.err
    assert 'secret-mid-value' not in out.out + out.err
    assert API_KEY not in out.out + out.err
    assert set(w.render_auth) == {f'Bearer {API_KEY}'}


def test_env_keys_follows_the_cursor_until_the_last_page(
    sp: Any, world: World_, capsys: pytest.CaptureFixture[str]
) -> None:
    """More than one page of variables are all listed, paging with the last item's cursor."""
    w, _router = world
    w.env_vars['srv-web'] = [_nested(f'KEY_{n:03d}', 'v', f'c{n}') for n in range(130)]
    w.env_vars['srv-worker'] = [_nested('ONLY', 'v', 'c0')]

    assert run_main(sp, w, ['env-keys']) == 0

    lines = capsys.readouterr().out.splitlines()
    web_keys = lines[0].removeprefix('web: ').split(', ')
    assert len(web_keys) == 130
    assert web_keys[0] == 'KEY_000'
    assert web_keys[-1] == 'KEY_129'
    web_queries = w.env_get_queries[:2]
    assert web_queries[0].get('cursor') is None
    assert web_queries[1]['cursor'] == 'c99'
    assert all(q['limit'] == '100' for q in w.env_get_queries)


def test_set_env_puts_the_value_on_web_and_worker_and_never_prints_it(
    sp: Any, world: World_, capsys: pytest.CaptureFixture[str]
) -> None:
    """PUT /services/{id}/env-vars/{KEY} with {"value": VALUE} on both, then one quiet line."""
    w, _router = world

    code = run_main(
        sp, w, ['set-env', 'PAYPAL_LOGIN_REDIRECT_URI', 'https://x.example/cb?s=topsecret']
    )

    assert code == 0
    assert w.env_puts == [
        ('srv-web', 'PAYPAL_LOGIN_REDIRECT_URI', {'value': 'https://x.example/cb?s=topsecret'}),
        ('srv-worker', 'PAYPAL_LOGIN_REDIRECT_URI', {'value': 'https://x.example/cb?s=topsecret'}),
    ]
    captured = capsys.readouterr()
    assert captured.out.strip() == 'set PAYPAL_LOGIN_REDIRECT_URI on web and worker'
    assert 'topsecret' not in captured.out + captured.err
    assert set(w.render_auth) == {f'Bearer {API_KEY}'}


def test_set_env_names_the_status_but_never_the_value_when_render_refuses(
    sp: Any, world: World_, capsys: pytest.CaptureFixture[str]
) -> None:
    """A non-2xx PUT ends non-zero; stderr carries the status and not the value."""
    w, _router = world
    w.env_put_status = 422

    code = run_main(sp, w, ['set-env', 'SOME_KEY', 'topsecret-value'])

    assert code == 1
    captured = capsys.readouterr()
    assert '422' in captured.err
    assert 'topsecret-value' not in captured.out + captured.err
    assert len(w.env_puts) == 1


def test_set_env_refuses_the_render_api_key_name(
    sp: Any, world: World_, capsys: pytest.CaptureFixture[str]
) -> None:
    """RENDER_API_KEY must never be pushed to the services; nothing is sent."""
    w, _router = world

    code = run_main(sp, w, ['set-env', 'RENDER_API_KEY', 'topsecret-value'])

    assert code != 0
    assert w.env_puts == []
    captured = capsys.readouterr()
    assert 'RENDER_API_KEY' in captured.err
    assert 'topsecret-value' not in captured.out + captured.err


# -- logs and run-job (plan 01-14) ---------------------------------------------------------------


def run_main_at(
    sp: Any, w: World, argv: Sequence[str], env: Mapping[str, str] | None = None
) -> int:
    """Run `main` like `run_main` but with the fixed clock the logs window is computed from."""
    code: int = sp.main(
        list(argv),
        env=dict(ENV if env is None else env),
        runner=w.run,
        sleep=w.sleep,
        monotonic=w.monotonic,
        utcnow=lambda: NOW,
    )
    return code


def _log(timestamp: str, message: str) -> dict[str, Any]:
    """One Render log entry: id, message, timestamp and labels."""
    return {
        'id': f'id-{timestamp}',
        'message': message,
        'timestamp': timestamp,
        'labels': [{'name': 'resource', 'value': 'srv-web'}],
    }


def test_logs_queries_the_web_service_for_the_window_and_prints_oldest_first(
    sp: Any, world: World_, capsys: pytest.CaptureFixture[str]
) -> None:
    """Render answers newest first; the output is chronological `timestamp message` lines only."""
    w, _router = world
    w.log_pages = [
        {
            'logs': [
                _log('2026-10-29T11:59:30Z', 'third line'),
                _log('2026-10-29T11:58:00Z', 'second line'),
                _log('2026-10-29T11:57:00Z', 'first line'),
            ]
        }
    ]

    code = run_main_at(sp, w, ['logs', '--minutes', '30', '--limit', '3'])

    assert code == 0
    (query,) = w.log_queries
    assert query['ownerId'] == OWNER_ID
    assert query['resource'] == 'srv-web'
    assert query['limit'] == '3'
    assert query['direction'] == 'backward'
    assert query['startTime'] == '2026-10-29T11:30:00Z'
    assert query['endTime'] == '2026-10-29T12:00:00Z'
    assert 'text' not in query
    assert capsys.readouterr().out.splitlines() == [
        '2026-10-29T11:57:00Z first line',
        '2026-10-29T11:58:00Z second line',
        '2026-10-29T11:59:30Z third line',
    ]


def test_logs_defaults_to_the_last_fifteen_minutes_of_the_web_service(
    sp: Any, world: World_
) -> None:
    w, _router = world

    assert run_main_at(sp, w, ['logs']) == 0

    (query,) = w.log_queries
    assert query['resource'] == 'srv-web'
    assert query['startTime'] == '2026-10-29T11:45:00Z'
    assert query['limit'] == '100'


def test_logs_can_target_the_worker_and_filter_by_text(sp: Any, world: World_) -> None:
    w, _router = world

    code = run_main_at(
        sp, w, ['logs', '--service', 'worker', '--text', 'hold.placed', '--limit', '40']
    )

    assert code == 0
    (query,) = w.log_queries
    assert query['resource'] == 'srv-worker'
    assert query['text'] == 'hold.placed'
    assert query['limit'] == '40'


def _page(start_second: int, count: int, prefix: str) -> list[dict[str, Any]]:
    """Return `count` log entries, newest first, one second apart, ending at `start_second`."""
    return [
        _log(
            f'2026-10-29T11:{(start_second - n) // 60:02d}:{(start_second - n) % 60:02d}Z',
            f'{prefix}{n}',
        )
        for n in range(count)
    ]


def test_logs_follows_the_pages_until_the_limit_is_reached(
    sp: Any, world: World_, capsys: pytest.CaptureFixture[str]
) -> None:
    """A limit above Render page size of 100 pages through hasMore and trims to the limit."""
    w, _router = world
    w.log_pages = [
        {
            'logs': _page(3599, 100, 'a'),
            'hasMore': True,
            'nextStartTime': '2026-10-29T11:00:00Z',
            'nextEndTime': '2026-10-29T11:58:00Z',
        },
        {'logs': _page(3400, 100, 'b'), 'hasMore': True, 'nextStartTime': 'x', 'nextEndTime': 'y'},
    ]

    code = run_main_at(sp, w, ['logs', '--minutes', '120', '--limit', '150'])

    assert code == 0
    assert [q['limit'] for q in w.log_queries] == ['100', '50']
    assert w.log_queries[1]['startTime'] == '2026-10-29T11:00:00Z'
    assert w.log_queries[1]['endTime'] == '2026-10-29T11:58:00Z'
    assert len(capsys.readouterr().out.splitlines()) == 150


def test_logs_never_prints_the_render_key_or_the_label_blob(
    sp: Any, world: World_, capsys: pytest.CaptureFixture[str]
) -> None:
    w, _router = world
    w.log_pages = [{'logs': [_log('2026-10-29T11:59:00Z', 'hello')]}]

    run_main_at(sp, w, ['logs'])

    captured = capsys.readouterr()
    assert 'hello' in captured.out
    assert API_KEY not in captured.out + captured.err
    assert 'labels' not in captured.out
    assert set(w.render_auth) == {f'Bearer {API_KEY}'}


def test_logs_names_the_status_when_render_refuses(
    sp: Any, world: World_, capsys: pytest.CaptureFixture[str]
) -> None:
    w, _router = world
    w.logs_status = 500

    code = run_main_at(sp, w, ['logs'])

    assert code == 1
    captured = capsys.readouterr()
    assert '500' in captured.err
    assert API_KEY not in captured.out + captured.err


def test_logs_fails_clearly_when_the_service_has_no_owner_id(
    sp: Any, world: World_, capsys: pytest.CaptureFixture[str]
) -> None:
    w, _router = world
    w.service_owner = None

    assert run_main_at(sp, w, ['logs']) == 1
    assert 'ownerId' in capsys.readouterr().err
    assert w.log_queries == []


def test_run_job_creates_a_job_on_the_web_service_polls_and_prints_its_logs(
    sp: Any, world: World_, capsys: pytest.CaptureFixture[str]
) -> None:
    w, _router = world
    w.job_statuses = ['pending', 'running', 'succeeded']
    w.log_pages = [
        {
            'logs': [
                _log('2026-10-29T12:00:10Z', 'job started'),
                _log('2026-10-29T12:00:20Z', 'job ok'),
            ]
        }
    ]

    code = run_main_at(sp, w, ['run-job', 'python scripts/spikes/x.py --run-id r1'])

    assert code == 0
    assert w.job_posts == [('srv-web', {'startCommand': 'python scripts/spikes/x.py --run-id r1'})]
    assert w.job_polls == ['job-123', 'job-123', 'job-123']
    assert w.sleeps[:2] == [5.0, 5.0]
    (query,) = w.log_queries
    assert query['resource'] == 'job-123'
    assert query['ownerId'] == OWNER_ID
    assert query['direction'] == 'forward'
    out = capsys.readouterr().out
    assert 'job-123' in out
    assert 'succeeded' in out
    assert '2026-10-29T12:00:10Z job started' in out
    assert '2026-10-29T12:00:20Z job ok' in out
    assert API_KEY not in out


def test_run_job_exits_non_zero_when_the_job_fails_but_still_prints_its_logs(
    sp: Any, world: World_, capsys: pytest.CaptureFixture[str]
) -> None:
    w, _router = world
    w.job_statuses = ['running', 'failed']
    w.log_pages = [{'logs': [_log('2026-10-29T12:00:10Z', 'Traceback boom')]}]

    code = run_main_at(sp, w, ['run-job', 'python boom.py'])

    assert code == 1
    out = capsys.readouterr().out
    assert 'failed' in out
    assert 'Traceback boom' in out


def test_run_job_exits_non_zero_for_a_cancelled_job(sp: Any, world: World_) -> None:
    w, _router = world
    w.job_statuses = ['canceled']

    assert run_main_at(sp, w, ['run-job', 'true']) == 1


def test_run_job_times_out_without_cancelling_and_names_the_job(
    sp: Any, world: World_, capsys: pytest.CaptureFixture[str]
) -> None:
    """A hung job keeps running (it may be mid-money-call); the tool reports it, never cancels."""
    w, _router = world
    w.job_statuses = ['running']

    code = run_main_at(sp, w, ['run-job', 'sleep 999', '--timeout', '30'])

    assert code == 1
    assert w.job_cancels == []
    assert w.now <= 30 + 10
    captured = capsys.readouterr()
    assert 'job-123' in captured.out + captured.err
    assert 'running' in captured.out + captured.err
    assert w.log_queries  # the logs so far are still printed


def test_run_job_stops_when_render_refuses_to_create_the_job(
    sp: Any, world: World_, capsys: pytest.CaptureFixture[str]
) -> None:
    w, _router = world
    w.job_create_status = 400

    code = run_main_at(sp, w, ['run-job', 'python x.py'])

    assert code == 1
    assert w.job_polls == []
    captured = capsys.readouterr()
    assert '400' in captured.err
    assert API_KEY not in captured.out + captured.err


def test_run_job_does_not_echo_the_command_it_was_given(
    sp: Any, world: World_, capsys: pytest.CaptureFixture[str]
) -> None:
    w, _router = world

    run_main_at(sp, w, ['run-job', 'python x.py --token=hunter2-not-for-output'])

    captured = capsys.readouterr()
    assert 'hunter2' not in captured.out + captured.err

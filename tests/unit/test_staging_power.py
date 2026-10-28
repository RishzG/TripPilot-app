"""Unit tests for scripts/ops/staging_power.py (01-07): the staging suspend/resume tool.

The Render API and the staging health endpoint are mocked with respx, and the subprocess runner
(`gh` and the persistence smoke script) is a recording fake, so nothing here touches a network,
GitHub or a real process. Time is a fake clock, so the bounded polls finish instantly.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from collections.abc import Iterator, Mapping, Sequence
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

    def _render_response(self, request: httpx.Request) -> httpx.Response:
        self.events.append(('http', request.method, str(request.url)))
        self.render_auth.append(request.headers.get('authorization'))
        if request.method == 'GET':
            state = self.status_bodies.get(str(request.url), 'not_suspended')
            return httpx.Response(200, json={'id': 'x', 'suspended': state})
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

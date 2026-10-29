"""Staging power tool (01-07, UD-5): suspend, resume and prove restarts of the staging stack.

Staging (Render web, worker and Postgres) is paid from the one-time hackathon credit, so it runs
only while someone needs it. This script drives it through the Render API:

    status         print web, worker and database state and whether staging is active
    resume         resume Postgres, web, worker; wait for /api/health; open the deploy gate
                   (repo variable STAGING_ACTIVE=true) and dispatch `release` so the current
                   main sha is deployed
    suspend        close the deploy gate first, then suspend worker, web and Postgres
    restart-proof  create a smoke trip, restart web and worker, wait for a new process start
                   time and a fresh worker heartbeat, then read the trip back

Configuration: RENDER_API_KEY, STAGING_BASE_URL, STAGING_WEB_SERVICE_ID, STAGING_WORKER_SERVICE_ID
and STAGING_DB_ID, read from the git-ignored .env.staging at the repo root (another path with
STAGING_ENV_FILE); variables already set in the environment win over the file, so sourcing the
file first still works. Every `gh` call names its repository with `--repo` (module constant
`GH_REPO_DEFAULT`, overridable with the GH_REPO environment variable), because this checkout's
default `gh` repository is the wrong upstream. The Render API key goes only into the Render
`Authorization` header: it is never printed, logged, passed to a subprocess or sent to staging.

Render endpoints used (api-docs.render.com): `GET /v1/services/{id}`, `GET /v1/postgres/{id}`,
`POST /v1/services/{id}/suspend|resume|restart` and `POST /v1/postgres/{id}/suspend|resume`.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import httpx

GH_REPO_DEFAULT = 'RishzG/TripPilot-app'
RENDER_API = 'https://api.render.com/v1'
HEALTH_PATH = '/api/health'
POLL_SECONDS = 5.0
FRESH_WORKER_SECONDS = 60.0
DEFAULT_RESUME_TIMEOUT = 600
DEFAULT_RESTART_TIMEOUT = 180
HTTP_TIMEOUT_SECONDS = 30.0
SUBPROCESS_TIMEOUT_SECONDS = 180.0
SMOKE_SCRIPT = Path(__file__).resolve().parents[1] / 'smoke' / 'hosted_persistence.py'
ENV_FILE_DEFAULT = Path(__file__).resolve().parents[2] / '.env.staging'
REQUIRED_ENV = (
    'RENDER_API_KEY',
    'STAGING_BASE_URL',
    'STAGING_WEB_SERVICE_ID',
    'STAGING_WORKER_SERVICE_ID',
    'STAGING_DB_ID',
)

Runner = Callable[[Sequence[str]], subprocess.CompletedProcess[str]]


class StagingError(Exception):
    """A staging step failed; the message names the step and a status, never a secret."""


@dataclass(frozen=True)
class Config:
    """Where staging lives and how to talk to Render about it."""

    api_key: str = field(repr=False)
    base_url: str
    web_id: str
    worker_id: str
    db_id: str


def load_env_file(path: Path) -> dict[str, str]:
    """Parse a dotenv-style file into a mapping; a missing file is an empty mapping.

    Accepts `KEY=value`, an optional `export ` prefix, surrounding single or double quotes, blank
    lines, `#` comments and a leading UTF-8 BOM (Notepad writes one). Lines without `=` are skipped.
    Values are never printed.
    """
    if not path.is_file():
        return {}
    values: dict[str, str] = {}
    for raw in path.read_text(encoding='utf-8-sig').splitlines():
        line = raw.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        key = key.strip().removeprefix('export ').strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
            value = value[1:-1]
        if key:
            values[key] = value
    return values


def load_config(env: Mapping[str, str]) -> Config:
    """Build a `Config` from the environment; raise `StagingError` naming missing variables."""
    missing = [name for name in REQUIRED_ENV if not env.get(name)]
    if missing:
        raise StagingError('missing environment variables: ' + ', '.join(missing))
    return Config(
        api_key=env['RENDER_API_KEY'],
        base_url=env['STAGING_BASE_URL'].rstrip('/'),
        web_id=env['STAGING_WEB_SERVICE_ID'],
        worker_id=env['STAGING_WORKER_SERVICE_ID'],
        db_id=env['STAGING_DB_ID'],
    )


def run_subprocess(argv: Sequence[str]) -> subprocess.CompletedProcess[str]:
    """Run a command with captured text output and no shell; never raises on a non-zero exit."""
    try:
        return subprocess.run(  # noqa: S603 - argv is built by this script, never through a shell
            list(argv),
            capture_output=True,
            text=True,
            check=False,
            timeout=SUBPROCESS_TIMEOUT_SECONDS,
        )
    except FileNotFoundError as error:
        raise StagingError(f'command not found: {argv[0]}') from error
    except subprocess.TimeoutExpired as error:
        raise StagingError(f'{Path(str(argv[0])).name} timed out') from error


class StagingPower:
    """The staging suspend/resume/restart operations, with injectable HTTP, processes and time."""

    def __init__(
        self,
        config: Config,
        client: httpx.Client,
        runner: Runner,
        *,
        repo: str = GH_REPO_DEFAULT,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        """Bind the configuration and the collaborators."""
        self._config = config
        self._client = client
        self._runner = runner
        self._repo = repo
        self._sleep = sleep
        self._monotonic = monotonic

    # -- plumbing ----------------------------------------------------------------------------

    def _render(self, method: str, path: str) -> httpx.Response:
        """Call the Render API; any non-2xx or transport failure raises `StagingError`."""
        try:
            response = self._client.request(
                method,
                f'{RENDER_API}{path}',
                headers={
                    'Authorization': f'Bearer {self._config.api_key}',
                    'Accept': 'application/json',
                },
            )
        except httpx.HTTPError as error:
            raise StagingError(f'Render {method} {path} failed: {type(error).__name__}') from error
        if not response.is_success:
            raise StagingError(f'Render {method} {path} returned HTTP {response.status_code}')
        return response

    def _gh(self, *args: str) -> None:
        """Run `gh <args> --repo <repo>`; a non-zero exit raises `StagingError`."""
        argv = ['gh', *args, '--repo', self._repo]
        completed = self._runner(argv)
        if completed.returncode != 0:
            detail = completed.stderr.strip()
            suffix = f': {detail}' if detail else ''
            raise StagingError(
                f'gh {" ".join(args[:2])} failed (exit {completed.returncode}){suffix}'
            )

    def _health(self) -> dict[str, object] | None:
        """Read staging /api/health (no credentials); None when it is not a 200 JSON object."""
        try:
            response = self._client.get(f'{self._config.base_url}{HEALTH_PATH}')
            body = response.json() if response.status_code == 200 else None
        except (httpx.HTTPError, ValueError):
            return None
        return body if isinstance(body, dict) else None

    def _wait_for(
        self, ready: Callable[[dict[str, object]], bool], timeout: int, what: str
    ) -> None:
        """Poll /api/health every few seconds until `ready` is true, or fail after `timeout`."""
        deadline = self._monotonic() + timeout
        while True:
            body = self._health()
            if body is not None and ready(body):
                return
            if self._monotonic() >= deadline:
                raise StagingError(f'{what} did not happen within {timeout} seconds')
            self._sleep(POLL_SECONDS)

    # -- commands ----------------------------------------------------------------------------

    def status(self) -> int:
        """Print each resource's state; staging is active only if none of the three is suspended."""
        resources = (
            ('web', f'/services/{self._config.web_id}'),
            ('worker', f'/services/{self._config.worker_id}'),
            ('database', f'/postgres/{self._config.db_id}'),
        )
        active = True
        for label, path in resources:
            body = self._render('GET', path).json()
            running = isinstance(body, dict) and body.get('suspended') == 'not_suspended'
            active = active and running
            print(f'{label}: {"active" if running else "suspended"}')
        print('staging: active' if active else 'staging: not active')
        return 0

    def resume(self, timeout: int = DEFAULT_RESUME_TIMEOUT) -> int:
        """Resume Postgres, web and worker, wait for health, then open the deploy gate."""
        self._render('POST', f'/postgres/{self._config.db_id}/resume')
        self._render('POST', f'/services/{self._config.web_id}/resume')
        self._render('POST', f'/services/{self._config.worker_id}/resume')
        print('resume requested for database, web and worker; waiting for /api/health')
        self._wait_for(lambda body: body.get('db') == 'ok', timeout, 'staging becoming healthy')
        self._gh('variable', 'set', 'STAGING_ACTIVE', '--body', 'true')
        self._gh('workflow', 'run', 'release.yml', '--ref', 'main')
        print('staging is up; STAGING_ACTIVE=true and the release workflow dispatched for main')
        return 0

    def suspend(self) -> int:
        """Close the deploy gate, then suspend worker, web and Postgres."""
        self._gh('variable', 'set', 'STAGING_ACTIVE', '--body', 'false')
        self._render('POST', f'/services/{self._config.worker_id}/suspend')
        self._render('POST', f'/services/{self._config.web_id}/suspend')
        self._render('POST', f'/postgres/{self._config.db_id}/suspend')
        print('staging suspended; STAGING_ACTIVE=false')
        return 0

    def _smoke(self, *extra: str) -> subprocess.CompletedProcess[str]:
        """Run the persistence smoke script against staging, relaying its diagnostics."""
        argv = [sys.executable, str(SMOKE_SCRIPT), self._config.base_url, *extra]
        completed = self._runner(argv)
        if completed.stderr:
            print(completed.stderr.rstrip(), file=sys.stderr)
        return completed

    def restart_proof(self, timeout: int = DEFAULT_RESTART_TIMEOUT) -> int:
        """Create a trip, restart web and worker, wait for a fresh process, read the trip back."""
        created = self._smoke()
        trip_id = created.stdout.strip()
        if created.returncode != 0 or not trip_id:
            raise StagingError('could not create the smoke trip before the restart')
        before = self._health()
        started_before = before.get('started_at') if before else None
        if not isinstance(started_before, str):
            raise StagingError('staging /api/health did not report started_at before the restart')

        self._render('POST', f'/services/{self._config.web_id}/restart')
        self._render('POST', f'/services/{self._config.worker_id}/restart')
        print(f'restarted web and worker (process started at {started_before}); waiting')

        def restarted(body: dict[str, object]) -> bool:
            age = body.get('worker_last_seen_seconds')
            fresh = (
                isinstance(age, int | float)
                and not isinstance(age, bool)
                and age < FRESH_WORKER_SECONDS
            )
            return body.get('started_at') != started_before and fresh

        self._wait_for(
            restarted, timeout, 'a new process start time with a worker heartbeat under 60 seconds'
        )
        if self._smoke('--check', trip_id).returncode != 0:
            raise StagingError(f'trip {trip_id} was not readable after the restart')
        print(f'restart proof passed: trip {trip_id} survived the restart')
        return 0


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser."""
    parser = argparse.ArgumentParser(description='Suspend, resume and prove restarts of staging.')
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('status', help='print web, worker and database state')
    resume = commands.add_parser('resume', help='resume staging and deploy the current main')
    resume.add_argument('--timeout', type=int, default=DEFAULT_RESUME_TIMEOUT, help='seconds')
    commands.add_parser('suspend', help='suspend staging and close the deploy gate')
    proof = commands.add_parser('restart-proof', help='prove a trip survives a restart')
    proof.add_argument('--timeout', type=int, default=DEFAULT_RESTART_TIMEOUT, help='seconds')
    return parser


def main(
    argv: Sequence[str],
    *,
    env: Mapping[str, str] | None = None,
    runner: Runner | None = None,
    sleep: Callable[[float], None] | None = None,
    monotonic: Callable[[], float] | None = None,
) -> int:
    """Run one subcommand; return 0 on success, 1 on a failed step and 2 on missing settings."""
    args = build_parser().parse_args(list(argv))
    if env is None:
        env_file = Path(os.environ.get('STAGING_ENV_FILE') or ENV_FILE_DEFAULT)
        environment: Mapping[str, str] = {**load_env_file(env_file), **os.environ}
    else:
        environment = env
    try:
        config = load_config(environment)
    except StagingError as error:
        print(f'error: {error}', file=sys.stderr)
        return 2
    repo = environment.get('GH_REPO') or GH_REPO_DEFAULT
    with httpx.Client(timeout=HTTP_TIMEOUT_SECONDS) as client:
        power = StagingPower(
            config,
            client,
            runner or run_subprocess,
            repo=repo,
            sleep=sleep or time.sleep,
            monotonic=monotonic or time.monotonic,
        )
        try:
            if args.command == 'status':
                return power.status()
            if args.command == 'resume':
                return power.resume(args.timeout)
            if args.command == 'suspend':
                return power.suspend()
            return power.restart_proof(args.timeout)
        except StagingError as error:
            print(f'error: {error}', file=sys.stderr)
            return 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))

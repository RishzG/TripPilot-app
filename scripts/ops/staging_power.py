"""Render power tool (01-07, 01-17, UD-5): suspend, resume and prove restarts of a hosted stack.

Staging and production (Render web, worker and Postgres) are paid from the one-time hackathon
credit, so each runs only while someone needs it. This script drives them through the Render API;
`--target staging` (the default) or `--target production` picks the stack:

    status         print web, worker and database state and whether the stack is active
    resume         resume Postgres, web, worker; wait for /api/health. Staging then opens its
                   deploy gate (repo variable STAGING_ACTIVE=true) and dispatches `release` so the
                   current main sha is deployed; production keeps the image it last ran (only the
                   `promote` workflow changes production's image)
    suspend        staging: close the deploy gate first, then suspend worker, web and Postgres.
                   production: suspend worker, web and Postgres, refused from
                   PRODUCTION_ALWAYS_ON_FROM (Nov 5) unless --force, because from then on judges
                   and the demo need it up
    restart-proof  create a smoke trip, restart web and worker, wait for a new process start
                   time and a fresh worker heartbeat, then read the trip back
    env-keys       print only the NAMES of the environment variables set on web and worker
    set-env KEY V  set one environment variable on both web and worker (value never printed)
    logs           print recent log lines (--minutes, --service web|worker, --limit, --text)
    run-job CMD    run CMD as a one-off Render job on the web service's latest build and env,
                   wait for it, print its logs, and exit 0 only if it succeeded (--timeout)

Configuration: RENDER_API_KEY, STAGING_BASE_URL, STAGING_WEB_SERVICE_ID, STAGING_WORKER_SERVICE_ID
and STAGING_DB_ID, read from the git-ignored .env.staging at the repo root (another path with
STAGING_ENV_FILE); for `--target production` the same names with the PRODUCTION_ prefix, read from
.env.production (another path with PRODUCTION_ENV_FILE). Variables already set in the environment
win over the file, so sourcing the file first still works, and the `production-power` GitHub
workflow passes them as environment variables with no file at all. Every `gh` call names its
repository with `--repo` (module constant `GH_REPO_DEFAULT`, overridable with the GH_REPO
environment variable), because this checkout's default `gh` repository is the wrong upstream. The
Render API key goes only into the Render `Authorization` header: it is never printed, logged,
passed to a subprocess or sent to the app.

Render endpoints used (api-docs.render.com): `GET /v1/services/{id}`, `GET /v1/postgres/{id}`,
`POST /v1/services/{id}/suspend|resume|restart`, `POST /v1/postgres/{id}/suspend|resume`,
`GET /v1/services/{id}/env-vars` (a JSON array of `{"envVar": {"key", "value"}, "cursor"}`,
paged with `?limit=` up to 100 and `?cursor=` of the last item) and
`PUT /v1/services/{id}/env-vars/{KEY}` with body `{"value": "..."}` (answers 200 `{"key","value"}`).
The env commands exist because the secret-read guard stops an interactive shell from sourcing
the env file: they print key names only and never a value.

Logs and one-off jobs (plan 01-14, confirmed against api-docs.render.com on 2026-10-29):
`GET /v1/services/{id}` supplies `ownerId` (the workspace id the logs API requires);
`GET /v1/logs?ownerId=&resource=<service or job id>&startTime=&endTime=&direction=&limit=` (limit
1 to 100; `text` is a substring search, wildcards and /regex/ allowed) answers
`{"logs": [{"id", "message", "timestamp", "labels"}], "hasMore", "nextStartTime", "nextEndTime"}`
and is paged by passing the next window back; `POST /v1/services/{id}/jobs` with
`{"startCommand": ...}` answers `{"id", "serviceId", "startCommand", "planId", "createdAt"}`;
`GET /v1/services/{id}/jobs/{jobId}` adds `status` (pending, running, succeeded, failed,
canceled), `startedAt` and `finishedAt`. A job reuses the base service's latest successful build
artifact and its environment variables as they were when the job was created; the job id is the
log `resource`. A job's command is never echoed (it may carry a secret) and a job that outlives
`--timeout` is reported, never cancelled, because it may be in the middle of a PayPal call.
"""

from __future__ import annotations

import argparse
import io
import os
import re
import subprocess
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
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
ENV_PAGE_LIMIT = 100
ENV_MAX_PAGES = 50
PROTECTED_ENV_KEYS = frozenset({'RENDER_API_KEY'})
DEFAULT_LOG_MINUTES = 15
DEFAULT_LOG_LIMIT = 100
LOG_PAGE_LIMIT = 100
LOG_MAX_PAGES = 30
DEFAULT_JOB_TIMEOUT = 600
JOB_LOG_LIMIT = 1000
JOB_LOG_ATTEMPTS = 3
JOB_LOG_PAD = timedelta(seconds=60)
JOB_TERMINAL_STATUSES = frozenset({'succeeded', 'failed', 'canceled'})
SUBPROCESS_TIMEOUT_SECONDS = 180.0
SMOKE_SCRIPT = Path(__file__).resolve().parents[1] / 'smoke' / 'hosted_persistence.py'
REPO_ROOT = Path(__file__).resolve().parents[2]
TARGETS = ('staging', 'production')
ENV_FILE_DEFAULTS = {
    'staging': REPO_ROOT / '.env.staging',
    'production': REPO_ROOT / '.env.production',
}
ENV_FILE_OVERRIDES = {'staging': 'STAGING_ENV_FILE', 'production': 'PRODUCTION_ENV_FILE'}
# From this moment production stays up through Dec 21 (hosted checkpoint, demo video, judging).
PRODUCTION_ALWAYS_ON_FROM = datetime(2026, 11, 5, tzinfo=UTC)


def required_env(target: str) -> tuple[str, ...]:
    """Return the variable names a target needs, e.g. PRODUCTION_DB_ID for production."""
    prefix = target.upper()
    return (
        'RENDER_API_KEY',
        f'{prefix}_BASE_URL',
        f'{prefix}_WEB_SERVICE_ID',
        f'{prefix}_WORKER_SERVICE_ID',
        f'{prefix}_DB_ID',
    )


Runner = Callable[[Sequence[str]], subprocess.CompletedProcess[str]]


def _iso(moment: datetime) -> str:
    """Format a moment as the UTC timestamp Render's logs API takes (`2026-10-29T12:00:00Z`)."""
    return moment.astimezone(UTC).strftime('%Y-%m-%dT%H:%M:%SZ')


def _parse_time(value: object) -> datetime | None:
    """Parse one of Render's ISO 8601 timestamps (any offset), or None when absent or invalid."""
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _positive_int(raw: str) -> int:
    """Parse a command-line integer that must be at least 1."""
    try:
        value = int(raw)
    except ValueError as error:
        raise argparse.ArgumentTypeError(f'{raw!r} is not a whole number') from error
    if value < 1:
        raise argparse.ArgumentTypeError('must be at least 1')
    return value


class StagingError(Exception):
    """A power step failed; the message names the step and a status, never a secret."""


@dataclass(frozen=True)
class Config:
    """Where one stack (staging or production) lives and how to talk to Render about it."""

    api_key: str = field(repr=False)
    base_url: str
    web_id: str
    worker_id: str
    db_id: str
    target: str = 'staging'


ANSI_ESCAPE = re.compile(r'\x1b\[[0-9;]*[A-Za-z]')


def clean_log_message(message: str) -> str:
    """Strip the terminal colour codes Render puts in its deploy banners."""
    return ANSI_ESCAPE.sub('', message)


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


def load_config(env: Mapping[str, str], target: str = 'staging') -> Config:
    """Build a target's `Config` from the environment; raise `StagingError` naming missing ones."""
    missing = [name for name in required_env(target) if not env.get(name)]
    if missing:
        raise StagingError('missing environment variables: ' + ', '.join(missing))
    prefix = target.upper()
    return Config(
        api_key=env['RENDER_API_KEY'],
        base_url=env[f'{prefix}_BASE_URL'].rstrip('/'),
        web_id=env[f'{prefix}_WEB_SERVICE_ID'],
        worker_id=env[f'{prefix}_WORKER_SERVICE_ID'],
        db_id=env[f'{prefix}_DB_ID'],
        target=target,
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
    """The suspend/resume/restart operations of one stack, with injectable HTTP, processes, time."""

    def __init__(
        self,
        config: Config,
        client: httpx.Client,
        runner: Runner,
        *,
        repo: str = GH_REPO_DEFAULT,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
        utcnow: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        """Bind the configuration and the collaborators."""
        self._config = config
        self._client = client
        self._runner = runner
        self._repo = repo
        self._sleep = sleep
        self._monotonic = monotonic
        self._utcnow = utcnow

    # -- plumbing ----------------------------------------------------------------------------

    def _render(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, str] | None = None,
        body: Mapping[str, str] | None = None,
    ) -> httpx.Response:
        """Call the Render API; any non-2xx or transport failure raises `StagingError`.

        Errors name the method, path and status only: never the request body, which may be a secret.
        """
        try:
            response = self._client.request(
                method,
                f'{RENDER_API}{path}',
                params=params,
                json=body,
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

    @property
    def _production(self) -> bool:
        return self._config.target == 'production'

    def _health(self) -> dict[str, object] | None:
        """Read the stack's /api/health (no credentials); None when it is not a 200 JSON object."""
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
        """Print each resource's state; the stack is active only if none of the three is off."""
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
        name = self._config.target
        print(f'{name}: active' if active else f'{name}: not active')
        return 0

    def resume(self, timeout: int = DEFAULT_RESUME_TIMEOUT) -> int:
        """Resume Postgres, web and worker and wait for health; staging then opens its gate."""
        name = self._config.target
        self._render('POST', f'/postgres/{self._config.db_id}/resume')
        self._render('POST', f'/services/{self._config.web_id}/resume')
        self._render('POST', f'/services/{self._config.worker_id}/resume')
        print('resume requested for database, web and worker; waiting for /api/health')
        self._wait_for(lambda body: body.get('db') == 'ok', timeout, f'{name} becoming healthy')
        if self._production:
            sha = self._health_sha()
            print(f'production is up on the image it last ran ({sha}); suspend it when done')
            return 0
        self._gh('variable', 'set', 'STAGING_ACTIVE', '--body', 'true')
        self._gh('workflow', 'run', 'release.yml', '--ref', 'main')
        print('staging is up; STAGING_ACTIVE=true and the release workflow dispatched for main')
        return 0

    def _health_sha(self) -> str:
        """Return the git sha /api/health reports, or 'unknown'."""
        body = self._health()
        sha = body.get('git_sha') if body else None
        return sha if isinstance(sha, str) and sha else 'unknown'

    def suspend(self, *, force: bool = False) -> int:
        """Suspend worker, web and Postgres; staging closes its deploy gate first.

        Production refuses from PRODUCTION_ALWAYS_ON_FROM unless `force`, so nobody turns the
        judge-facing stack off by habit once the demo period starts.
        """
        if self._production:
            if self._utcnow() >= PRODUCTION_ALWAYS_ON_FROM and not force:
                raise StagingError(
                    f'production stays up from {PRODUCTION_ALWAYS_ON_FROM:%Y-%m-%d} through '
                    'Dec 21; pass --force only to stop an emergency'
                )
        else:
            self._gh('variable', 'set', 'STAGING_ACTIVE', '--body', 'false')
        self._render('POST', f'/services/{self._config.worker_id}/suspend')
        self._render('POST', f'/services/{self._config.web_id}/suspend')
        self._render('POST', f'/postgres/{self._config.db_id}/suspend')
        print(
            'production suspended'
            if self._production
            else 'staging suspended; STAGING_ACTIVE=false'
        )
        return 0

    def _service_env_keys(self, service_id: str) -> list[str]:
        """Return the sorted variable names of one service, following Render's cursor paging.

        Accepts the documented `{"envVar": {"key", "value"}, "cursor"}` items and flat
        `{"key", "value"}` items. Only keys are read out of each item; values are dropped here.
        """
        keys: list[str] = []
        cursor: str | None = None
        for _ in range(ENV_MAX_PAGES):
            params = {'limit': str(ENV_PAGE_LIMIT)}
            if cursor is not None:
                params['cursor'] = cursor
            page = self._render('GET', f'/services/{service_id}/env-vars', params=params).json()
            if not isinstance(page, list) or not page:
                break
            last_cursor: str | None = None
            for item in page:
                if not isinstance(item, dict):
                    continue
                entry = item.get('envVar', item)
                key = entry.get('key') if isinstance(entry, dict) else None
                if isinstance(key, str):
                    keys.append(key)
                if isinstance(item.get('cursor'), str):
                    last_cursor = item['cursor']
            if len(page) < ENV_PAGE_LIMIT or last_cursor is None:
                break
            cursor = last_cursor
        return sorted(set(keys))

    def env_keys(self) -> int:
        """Print the variable names set on web and worker, one line per service; no values."""
        for label, service_id in (('web', self._config.web_id), ('worker', self._config.worker_id)):
            print(f'{label}: {", ".join(self._service_env_keys(service_id))}')
        return 0

    def set_env(self, key: str, value: str) -> int:
        """Set one variable on web and worker; the value is sent to Render and never printed."""
        if key in PROTECTED_ENV_KEYS:
            raise StagingError(f'{key} is never copied to the {self._config.target} services')
        for service_id in (self._config.web_id, self._config.worker_id):
            self._render('PUT', f'/services/{service_id}/env-vars/{key}', body={'value': value})
        print(f'set {key} on web and worker')
        if self._production:
            print('it applies on the next deploy: promote the sha production already runs')
        return 0

    # -- logs and one-off jobs (plan 01-14) --------------------------------------------------

    def _owner_id(self, service_id: str) -> str:
        """Return the workspace id of a service; the Render logs API needs it."""
        body = self._render('GET', f'/services/{service_id}').json()
        owner = body.get('ownerId') if isinstance(body, dict) else None
        if not isinstance(owner, str) or not owner:
            raise StagingError('Render did not report an ownerId for the service')
        return owner

    def _fetch_logs(
        self,
        owner_id: str,
        resource_id: str,
        start: datetime,
        end: datetime,
        limit: int,
        *,
        direction: str,
        text: str | None = None,
    ) -> list[tuple[str, str]]:
        """Return up to `limit` (timestamp, message) pairs, oldest first, paging by time window.

        `direction='backward'` keeps the newest `limit` lines; `'forward'` the oldest. Only the
        timestamp and message of each entry are read: labels are dropped here.
        """
        window_start, window_end = _iso(start), _iso(end)
        entries: list[tuple[str, str]] = []
        for _ in range(LOG_MAX_PAGES):
            wanted = limit - len(entries)
            if wanted <= 0:
                break
            params = {
                'ownerId': owner_id,
                'resource': resource_id,
                'startTime': window_start,
                'endTime': window_end,
                'direction': direction,
                'limit': str(min(wanted, LOG_PAGE_LIMIT)),
            }
            if text:
                params['text'] = text
            body = self._render('GET', '/logs', params=params).json()
            if not isinstance(body, dict):
                break
            for item in body.get('logs') or []:
                if not isinstance(item, dict):
                    continue
                timestamp, message = item.get('timestamp'), item.get('message')
                if isinstance(timestamp, str) and isinstance(message, str):
                    entries.append((timestamp, message.rstrip('\n')))
            next_start, next_end = body.get('nextStartTime'), body.get('nextEndTime')
            if body.get('hasMore') is not True:
                break
            if not isinstance(next_start, str) or not isinstance(next_end, str):
                break
            window_start, window_end = next_start, next_end
        kept = entries[:limit]
        if direction == 'backward':
            kept.reverse()
        return kept

    def logs(self, minutes: int, service: str, limit: int, text: str | None) -> int:
        """Print the newest `limit` log lines of the web or worker service in a recent window."""
        service_id = self._config.web_id if service == 'web' else self._config.worker_id
        owner_id = self._owner_id(service_id)
        end = self._utcnow()
        lines = self._fetch_logs(
            owner_id,
            service_id,
            end - timedelta(minutes=minutes),
            end,
            limit,
            direction='backward',
            text=text,
        )
        for timestamp, message in lines:
            print(f'{timestamp} {clean_log_message(message)}')
        return 0

    def run_job(self, command: str, timeout: int = DEFAULT_JOB_TIMEOUT) -> int:
        """Run `command` as a one-off job on the web service, wait, print its logs.

        Returns 0 only when the job's final status is `succeeded`. The command is never printed
        and a job still running at the timeout is left running (it may be mid-call to PayPal).
        """
        service_id = self._config.web_id
        owner_id = self._owner_id(service_id)  # first, so a failure here runs nothing
        created = self._render(
            'POST', f'/services/{service_id}/jobs', body={'startCommand': command}
        ).json()
        job_id = created.get('id') if isinstance(created, dict) else None
        if not isinstance(job_id, str) or not job_id:
            raise StagingError('Render did not return a job id')
        print(f'job {job_id} created on the web service; waiting')
        created_at = _parse_time(created.get('createdAt')) or self._utcnow()

        deadline = self._monotonic() + timeout
        status = 'pending'
        finished_at: datetime | None = None
        while True:
            job = self._render('GET', f'/services/{service_id}/jobs/{job_id}').json()
            if isinstance(job, dict):
                if isinstance(job.get('status'), str):
                    status = job['status']
                finished_at = _parse_time(job.get('finishedAt')) or finished_at
            if status in JOB_TERMINAL_STATUSES or self._monotonic() >= deadline:
                break
            self._sleep(POLL_SECONDS)

        finished = status in JOB_TERMINAL_STATUSES
        print(f'job {job_id}: {status}')
        if not finished:
            print(
                f'error: job {job_id} was still {status} after {timeout} seconds; it was not '
                'cancelled (cancel it in the Render dashboard if it must stop)',
                file=sys.stderr,
            )
        end = (finished_at or self._utcnow()) + JOB_LOG_PAD
        try:
            lines: list[tuple[str, str]] = []
            for attempt in range(JOB_LOG_ATTEMPTS):
                if finished and attempt == 0:
                    self._sleep(POLL_SECONDS)  # log ingestion trails the job's exit
                lines = self._fetch_logs(
                    owner_id,
                    job_id,
                    created_at - JOB_LOG_PAD,
                    end,
                    JOB_LOG_LIMIT,
                    direction='forward',
                )
                if lines or not finished:
                    break
                self._sleep(POLL_SECONDS)
            for timestamp, message in lines:
                print(f'{timestamp} {clean_log_message(message)}')
        except StagingError as error:
            print(f'warning: could not read the job logs: {error}', file=sys.stderr)
        return 0 if status == 'succeeded' else 1

    def _smoke(self, *extra: str) -> subprocess.CompletedProcess[str]:
        """Run the persistence smoke script against the stack, relaying its diagnostics."""
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
            raise StagingError(
                f'{self._config.target} /api/health did not report started_at before the restart'
            )

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
    parser = argparse.ArgumentParser(
        description='Suspend, resume and prove restarts of staging or production.'
    )
    parser.add_argument('--target', choices=TARGETS, default='staging', help='which stack')
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('status', help='print web, worker and database state')
    resume = commands.add_parser(
        'resume', help='resume the stack (staging also deploys the current main)'
    )
    resume.add_argument('--timeout', type=int, default=DEFAULT_RESUME_TIMEOUT, help='seconds')
    suspend = commands.add_parser(
        'suspend', help='suspend the stack (staging also closes its deploy gate)'
    )
    suspend.add_argument(
        '--force', action='store_true', help='production only: suspend even from Nov 5'
    )
    proof = commands.add_parser('restart-proof', help='prove a trip survives a restart')
    proof.add_argument('--timeout', type=int, default=DEFAULT_RESTART_TIMEOUT, help='seconds')
    commands.add_parser('env-keys', help='print the names (never values) of the service env vars')
    set_env = commands.add_parser('set-env', help='set one env var on both web and worker')
    set_env.add_argument('key', help='variable name, e.g. PAYPAL_LOGIN_REDIRECT_URI')
    set_env.add_argument('value', help='variable value (sent to Render, never printed)')
    logs = commands.add_parser('logs', help='print recent log lines of the web or worker service')
    logs.add_argument('--minutes', type=_positive_int, default=DEFAULT_LOG_MINUTES)
    logs.add_argument('--service', choices=('web', 'worker'), default='web')
    logs.add_argument('--limit', type=_positive_int, default=DEFAULT_LOG_LIMIT)
    logs.add_argument('--text', help='only lines containing this text (Render allows * and /re/)')
    job = commands.add_parser('run-job', help='run one command as a one-off job on the web service')
    job.add_argument('job_command', metavar='COMMAND', help='the start command to run')
    job.add_argument('--timeout', type=_positive_int, default=DEFAULT_JOB_TIMEOUT, help='seconds')
    return parser


def main(
    argv: Sequence[str],
    *,
    env: Mapping[str, str] | None = None,
    runner: Runner | None = None,
    sleep: Callable[[float], None] | None = None,
    monotonic: Callable[[], float] | None = None,
    utcnow: Callable[[], datetime] | None = None,
) -> int:
    """Run one subcommand; return 0 on success, 1 on a failed step and 2 on missing settings."""
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            # Render log lines carry emoji a Windows console code page cannot encode.
            stream.reconfigure(errors='replace')
    args = build_parser().parse_args(list(argv))
    if env is None:
        override = os.environ.get(ENV_FILE_OVERRIDES[args.target])
        env_file = Path(override) if override else ENV_FILE_DEFAULTS[args.target]
        environment: Mapping[str, str] = {**load_env_file(env_file), **os.environ}
    else:
        environment = env
    try:
        config = load_config(environment, args.target)
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
            utcnow=utcnow or (lambda: datetime.now(UTC)),
        )
        try:
            if args.command == 'status':
                return power.status()
            if args.command == 'resume':
                return power.resume(args.timeout)
            if args.command == 'suspend':
                return power.suspend(force=args.force)
            if args.command == 'env-keys':
                return power.env_keys()
            if args.command == 'set-env':
                return power.set_env(args.key, args.value)
            if args.command == 'logs':
                return power.logs(args.minutes, args.service, args.limit, args.text)
            if args.command == 'run-job':
                return power.run_job(args.job_command, args.timeout)
            return power.restart_proof(args.timeout)
        except StagingError as error:
            print(f'error: {error}', file=sys.stderr)
            return 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))

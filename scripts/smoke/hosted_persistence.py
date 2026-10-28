"""Persistence smoke test usable against localhost and any hosted base URL.

Create mode signs in as the demo persona Maya, starts "Smoke trip <utc timestamp>" and prints
only the trip id on stdout (diagnostics go to stderr). Check mode signs in as Maya again and
asserts the trip is still readable with a "Smoke trip" name. Run create, restart or redeploy the
service, then run check with the printed id.

    uv run python scripts/smoke/hosted_persistence.py http://localhost:8000
    uv run python scripts/smoke/hosted_persistence.py http://localhost:8000 --check <trip-id>

The target must run with DEMO_MODE on. Exit status is non-zero on any failure.
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime

import httpx

PERSONA_SLUG = 'maya'
NAME_PREFIX = 'Smoke trip'
TIMEOUT_SECONDS = 20.0


class SmokeError(Exception):
    """A smoke step failed; the message names the step and the HTTP status, never a cookie."""


def log(message: str) -> None:
    """Write a diagnostic line to stderr so stdout stays clean for the trip id."""
    print(message, file=sys.stderr)


def sign_in(client: httpx.Client) -> None:
    """Sign the client in as the Maya persona; the session cookie stays in its jar."""
    response = client.post(f'/api/demo/personas/{PERSONA_SLUG}/session')
    if response.status_code != 200:
        raise SmokeError(f'persona sign-in failed with HTTP {response.status_code}')
    log(f'signed in as persona {PERSONA_SLUG}')


def create_trip(client: httpx.Client) -> str:
    """Create a timestamped smoke trip and return its id."""
    stamp = datetime.now(UTC).strftime('%Y-%m-%d %H:%M:%S')
    response = client.post('/api/trips', json={'name': f'{NAME_PREFIX} {stamp}'})
    if response.status_code != 201:
        raise SmokeError(f'creating the trip failed with HTTP {response.status_code}')
    trip_id = response.json().get('id')
    if not isinstance(trip_id, str) or not trip_id:
        raise SmokeError('create response carried no trip id')
    log(f'created trip {trip_id}')
    return trip_id


def check_trip(client: httpx.Client, trip_id: str) -> None:
    """Assert the trip is readable by the same persona and still has its smoke name."""
    response = client.get(f'/api/trips/{trip_id}')
    if response.status_code != 200:
        raise SmokeError(f'reading trip {trip_id} failed with HTTP {response.status_code}')
    name = response.json().get('name')
    if not isinstance(name, str) or not name.startswith(NAME_PREFIX):
        raise SmokeError(f'trip {trip_id} came back with an unexpected name')
    log(f'trip {trip_id} is still readable as "{name}"')


def run(base_url: str, check_id: str | None) -> int:
    """Run create mode (prints the trip id) or check mode against `base_url`."""
    with httpx.Client(base_url=base_url, timeout=TIMEOUT_SECONDS) as client:
        try:
            sign_in(client)
            if check_id is None:
                print(create_trip(client))
            else:
                check_trip(client, check_id)
        except (SmokeError, httpx.HTTPError, ValueError) as error:
            log(f'smoke failed: {error}')
            return 1
    return 0


def main(argv: list[str]) -> int:
    """Parse arguments and run the smoke."""
    parser = argparse.ArgumentParser(description='Trip persistence smoke test.')
    parser.add_argument('base_url', help='for example http://localhost:8000')
    parser.add_argument('--check', metavar='TRIP_ID', help='re-read this trip instead of creating')
    args = parser.parse_args(argv[1:])
    return run(args.base_url, args.check)


if __name__ == '__main__':
    sys.exit(main(sys.argv))

"""Print the pool-buyer enrolment checklist for one environment (plan 01-14, D-14, UD-1).

A checklist printer only: it makes no network call, reads no secret and never asks for, reads or
stores a sandbox password. Each buyer is enrolled by a human in the app's own admin page, where
PayPal's popup does the login (D-16). Staging gets maya, sam and ana; production gets leo, priya
and jules (01-17 runs the same page on the production app).

Run: ``uv run python scripts/spikes/enrol_pool_buyer.py [--base-url https://...] [--environment
staging|production]``. Without ``--base-url`` it uses the ``STAGING_BASE_URL`` environment
variable, then the ``STAGING_BASE_URL`` line of the git-ignored ``.env.staging`` (read at runtime;
nothing else in that file is looked at or printed).
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = REPO_ROOT / '.env.staging'
BASE_URL_KEY = 'STAGING_BASE_URL'

CHECKLISTS: dict[str, tuple[tuple[str, str], ...]] = {
    'staging': (('maya', 'maya'), ('sam', 'sam'), ('ana', 'ana')),
    'production': (('leo', 'leo'), ('priya', 'priya'), ('jules', 'jules')),
}
"""Environment -> (slug, persona slug) pairs the environment's pool needs (UD-1)."""


def base_url_from_env_file(path: Path) -> str | None:
    """Return the `STAGING_BASE_URL` value from a dotenv file, or None; no other line is used."""
    if not path.is_file():
        return None
    for raw in path.read_text(encoding='utf-8-sig').splitlines():
        line = raw.strip().removeprefix('export ').strip()
        if line.startswith(f'{BASE_URL_KEY}='):
            value = line.split('=', 1)[1].strip().strip('"').strip("'")
            return value or None
    return None


def resolve_base_url(explicit: str | None) -> str | None:
    """Pick the base URL: the flag, then the process environment, then `.env.staging`."""
    chosen = explicit or os.environ.get(BASE_URL_KEY) or base_url_from_env_file(ENV_FILE)
    return chosen.rstrip('/') if chosen else None


def checklist_lines(environment: str, base_url: str) -> list[str]:
    """Return the printable checklist for the environment's buyers."""
    pairs = CHECKLISTS[environment]
    pool_url = f'{base_url}/admin/pool'
    lines = [
        f'Enrol the {environment} pool buyers ({len(pairs)}): {", ".join(slug for slug, _ in pairs)}',
        '',
        f'1. Sign in at {base_url} with Log in with PayPal using an ADMIN_EMAILS account.',
        f'2. Open {pool_url} and add a row for each buyer below (slug, persona, sandbox email).',
        '3. For each row press Enrol, then Save PayPal. In the PayPal popup log in AS THAT',
        '   sandbox buyer and approve. You type the password into PayPal only; nothing here',
        '   asks for, reads or stores it.',
        '4. The row reads Enrolled and the page says "<Persona> is enrolled."',
        '',
        'Buyers to enrol:',
    ]
    for slug, persona in pairs:
        lines.append(f'  - slug {slug}   persona {persona}   sandbox email: <its personal account>')
        lines.append(f'      enrol page: {pool_url}/enrol/{slug}')
    lines += [
        '',
        'If the popup fails on a phone, use a desktop browser.',
        'Each buyer is saved once per environment (UD-1); saving again replaces the token.',
    ]
    return lines


def main(argv: list[str] | None = None) -> int:
    """Parse the command line and print the checklist."""
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0] if __doc__ else None)
    parser.add_argument(
        '--base-url', help='the app base URL, e.g. https://trippilot-staging-web.onrender.com'
    )
    parser.add_argument('--environment', choices=sorted(CHECKLISTS), default='staging')
    args = parser.parse_args(argv)
    base_url = resolve_base_url(args.base_url)
    if base_url is None:
        print(
            f'error: pass --base-url or set {BASE_URL_KEY} (environment or .env.staging)',
            file=sys.stderr,
        )
        return 2
    print('\n'.join(checklist_lines(args.environment, base_url)))
    return 0


if __name__ == '__main__':
    sys.exit(main())

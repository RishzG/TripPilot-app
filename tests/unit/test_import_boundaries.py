"""Money import boundaries, enforced inside pytest so CI needs no workflow change.

Two layers:

- import-linter runs `importlinter.ini` (contracts must not import payments; 01-08 extends it).
- A source scan covers packages no import-linter contract names yet (health, app, db, ...):
  nothing outside `trippilot.payments` may import `payments.client`, `payments.token_cache` or
  `payments.vault_store`. The scan parses imports with `ast`, so multi-line, aliased, relative
  and commented-out forms are all handled, and a docstring that merely mentions one is not.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from importlinter.cli import lint_imports

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / 'src'
PAYMENTS_DIR = SRC_ROOT / 'trippilot' / 'payments'
PAYMENTS = 'trippilot.payments'
PROTECTED = ('client', 'token_cache', 'vault_store')


def find_protected_imports(source: str, module: str, *, is_package: bool = False) -> list[int]:
    """Return the line numbers where `source` imports a protected payments internal.

    `module` is the dotted name of the file being scanned (needed to resolve relative imports);
    `is_package` is True for an `__init__.py`.
    """
    package_parts = module.split('.') if is_package else module.split('.')[:-1]
    hits: list[int] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            if any(_is_protected(alias.name) for alias in node.names):
                hits.append(node.lineno)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                keep = len(package_parts) - (node.level - 1)
                base = '.'.join(package_parts[: max(keep, 0)])
                target = f'{base}.{node.module}' if node.module else base
            else:
                target = node.module or ''
            if _is_protected(target) or (
                target == PAYMENTS and any(alias.name in PROTECTED for alias in node.names)
            ):
                hits.append(node.lineno)
    return sorted(hits)


def _is_protected(dotted: str) -> bool:
    """True for `trippilot.payments.<protected>` and anything beneath it."""
    return any(
        dotted == f'{PAYMENTS}.{name}' or dotted.startswith(f'{PAYMENTS}.{name}.')
        for name in PROTECTED
    )


def test_import_linter_contracts_pass() -> None:
    exit_code = lint_imports(config_filename=str(REPO_ROOT / 'importlinter.ini'), no_cache=True)

    assert exit_code == 0


def test_payments_internals_stay_inside_payments() -> None:
    scanned = 0
    offences: list[str] = []
    for path in sorted((SRC_ROOT / 'trippilot').rglob('*.py')):
        if PAYMENTS_DIR in path.parents:
            continue
        scanned += 1
        relative = path.relative_to(SRC_ROOT).with_suffix('')
        parts = relative.parts
        is_package = parts[-1] == '__init__'
        module = '.'.join(parts[:-1] if is_package else parts)
        for line in find_protected_imports(
            path.read_text(encoding='utf-8'), module, is_package=is_package
        ):
            offences.append(f'{path.relative_to(REPO_ROOT)}:{line}')

    assert scanned > 0, 'the scan found no files, so it proves nothing'
    assert not offences, f'imports of payments internals outside payments: {offences}'


@pytest.mark.parametrize(
    ('source', 'module'),
    [
        ('import trippilot.payments.client', 'trippilot.health'),
        ('import trippilot.payments.client as c', 'trippilot.health'),
        ('from trippilot.payments.client import PayPalClient', 'trippilot.app'),
        ('from trippilot.payments.token_cache import TokenCache', 'trippilot.db.engine'),
        ('from trippilot.payments.vault_store import VaultStore', 'trippilot.trips.service'),
        ('from trippilot.payments import client', 'trippilot.health'),
        ('from trippilot.payments import get_paypal_gateway, token_cache', 'trippilot.health'),
        (
            'from trippilot.payments import (\n    get_paypal_gateway,\n    vault_store,\n)',
            'trippilot.app',
        ),
        ('from .payments.client import PayPalClient', 'trippilot.health'),
        ('from ..payments.client import PayPalClient', 'trippilot.trips.service'),
        ('from ..payments import token_cache', 'trippilot.trips.service'),
        ('from .payments import client', 'trippilot.__init__'),
    ],
)
def test_matcher_flags_protected_imports(source: str, module: str) -> None:
    is_package = module.endswith('.__init__')
    name = module.removesuffix('.__init__')

    assert find_protected_imports(source, name, is_package=is_package) == [1]


@pytest.mark.parametrize(
    ('source', 'module'),
    [
        ('import trippilot.payments', 'trippilot.health'),
        ('from trippilot.payments import get_paypal_gateway', 'trippilot.health'),
        ('from trippilot.contracts.paypal import PayPalGateway', 'trippilot.health'),
        ('from .. import payments', 'trippilot.trips.service'),
        ('"""Docs mention import trippilot.payments.client in prose."""', 'trippilot.health'),
        ('# from trippilot.payments.client import PayPalClient', 'trippilot.health'),
        ('import httpx', 'trippilot.health'),
    ],
)
def test_matcher_ignores_allowed_imports(source: str, module: str) -> None:
    assert find_protected_imports(source, module) == []

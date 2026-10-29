"""The enrolment checklist printer (plan 01-14): URLs and slugs, never a password prompt."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / 'scripts' / 'spikes' / 'enrol_pool_buyer.py'
BASE = 'https://staging.example.test'


@pytest.fixture(scope='module')
def script() -> ModuleType:
    """Load scripts/spikes/enrol_pool_buyer.py by path (scripts/ is not a package)."""
    spec = importlib.util.spec_from_file_location('enrol_pool_buyer', SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules['enrol_pool_buyer'] = module
    spec.loader.exec_module(module)
    return module


def test_the_staging_checklist_names_maya_sam_ana_and_their_enrol_pages(
    script: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    assert script.main(['--base-url', f'{BASE}/']) == 0

    out = capsys.readouterr().out
    assert f'{BASE}/admin/pool' in out
    for slug in ('maya', 'sam', 'ana'):
        assert f'{BASE}/admin/pool/enrol/{slug}' in out
    for slug in ('leo', 'priya', 'jules'):
        assert slug not in out


def test_the_production_checklist_names_the_other_three(
    script: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    assert script.main(['--base-url', BASE, '--environment', 'production']) == 0

    out = capsys.readouterr().out
    for slug in ('leo', 'priya', 'jules'):
        assert f'{BASE}/admin/pool/enrol/{slug}' in out


def test_the_checklist_never_asks_for_a_password(
    script: Any, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(*_args: object, **_kwargs: object) -> str:
        raise AssertionError('the checklist must not prompt for anything')

    monkeypatch.setattr('builtins.input', refuse)
    monkeypatch.setattr('getpass.getpass', refuse)

    assert script.main(['--base-url', BASE]) == 0

    out = capsys.readouterr().out.lower()
    assert 'nothing here' in out
    assert 'enter your password' not in out


def test_a_missing_base_url_is_a_usage_error(
    script: Any,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.delenv('STAGING_BASE_URL', raising=False)
    monkeypatch.setattr(script, 'ENV_FILE', tmp_path / 'missing.env')

    assert script.main([]) == 2
    assert 'STAGING_BASE_URL' in capsys.readouterr().err


def test_the_base_url_comes_from_the_environment_then_the_env_file(
    script: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    env_file = tmp_path / '.env.staging'
    env_file.write_text('OTHER=1\nexport STAGING_BASE_URL="https://from-file.test/"\n')
    monkeypatch.setattr(script, 'ENV_FILE', env_file)
    monkeypatch.delenv('STAGING_BASE_URL', raising=False)

    assert script.resolve_base_url(None) == 'https://from-file.test'

    monkeypatch.setenv('STAGING_BASE_URL', 'https://from-env.test')
    assert script.resolve_base_url(None) == 'https://from-env.test'
    assert script.resolve_base_url('https://flag.test/') == 'https://flag.test'

"""The OpenAPI dump covers every SPA route whatever DEMO_MODE says (01-23, T-01-58)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / 'scripts' / 'dump_openapi.py'


def _dump(out: Path, demo_mode: str) -> dict[str, object]:
    """Run the dump script in a child process with DEMO_MODE set, and return the schema."""
    env = {**os.environ, 'DEMO_MODE': demo_mode}
    completed = subprocess.run(  # noqa: S603 - fixed interpreter and our own script path
        [sys.executable, str(SCRIPT), str(out)],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout == ''
    schema: dict[str, object] = json.loads(out.read_text(encoding='utf-8'))
    return schema


@pytest.mark.parametrize('demo_mode', ['false', 'true'])
def test_dump_includes_the_demo_and_trip_routes_in_every_environment(
    tmp_path: Path, demo_mode: str
) -> None:
    """The schema has the persona routes even with DEMO_MODE off in the caller's environment."""
    schema = _dump(tmp_path / 'openapi.json', demo_mode)
    paths = schema['paths']
    assert isinstance(paths, dict)
    assert '/api/demo/personas' in paths
    assert '/api/demo/personas/{slug}/session' in paths
    assert '/api/trips' in paths
    assert '/api/trips/{trip_id}' in paths


def test_dump_is_written_with_sorted_keys(tmp_path: Path) -> None:
    """Sorted keys keep the dump stable, so a regenerated client does not churn."""
    out = tmp_path / 'openapi.json'
    _dump(out, 'false')
    schema = json.loads(out.read_text(encoding='utf-8'))
    assert out.read_text(encoding='utf-8') == json.dumps(schema, indent=2, sort_keys=True) + '\n'

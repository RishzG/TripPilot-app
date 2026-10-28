"""Write the FastAPI OpenAPI schema to web/openapi.json for the SPA's generated types.

The schema is built with demo mode forced on, so the generated client covers every route the
SPA calls (including /api/demo/personas) whatever DEMO_MODE the caller's environment sets: the
CI frontend job, the Docker build stage and a local shell all produce the same types. The
override is a settings copy used for this dump only; the runtime app is built by `create_app()`
from the real settings, so the persona routes stay unmounted when DEMO_MODE is off (D-15).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from trippilot.app import create_app
from trippilot.settings import get_settings

DEFAULT_OUTPUT = Path(__file__).resolve().parents[1] / 'web' / 'openapi.json'


def main(argv: list[str]) -> int:
    """Write the schema to the path in `argv[1]`, or web/openapi.json when none is given."""
    output = Path(argv[1]) if len(argv) > 1 else DEFAULT_OUTPUT
    app = create_app(get_settings().model_copy(update={'demo_mode': True}))
    output.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(app.openapi(), indent=2, sort_keys=True) + '\n'
    output.write_text(text, encoding='utf-8')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))

"""Write the FastAPI OpenAPI document for the web type generator.

The web client's types are generated from this file rather than hand-written,
so a backend change that the client has not accounted for shows up as a type
error instead of as a runtime surprise (ADR-0006 decision 5).

Usage::

    uv run python scripts/export_openapi.py apps/web/openapi.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from codeatlas.api.app import create_app


def main(argv: list[str]) -> int:
    output = Path(argv[1]) if len(argv) > 1 else Path("apps/web/openapi.json")
    document = create_app(Path("codeatlas-openapi-placeholder.db")).openapi()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

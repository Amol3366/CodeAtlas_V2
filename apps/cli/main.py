"""CLI entrypoint shim.

The Typer application lives in `codeatlas.main` so the packaged console script
(`codeatlas = codeatlas.main:app`) and this app-level entrypoint share one
implementation (CLAUDE.md §4: adapters are thin).
"""

from __future__ import annotations

from codeatlas.main import app

if __name__ == "__main__":
    app()

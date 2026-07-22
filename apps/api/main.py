"""FastAPI application entrypoint (skeleton — Phase 0).

The full REST surface (Blueprint §12, docs/rest_contract.md) is implemented in
Phase 7. For now this exposes only a health endpoint so the app object exists and
`scripts/run_dev.ps1` can boot it. Routes are thin adapters over application
services (CLAUDE.md §4) and must never re-implement repository logic.
"""

from __future__ import annotations

from fastapi import FastAPI

from codeatlas import __version__

app = FastAPI(
    title="CodeAtlas",
    version=__version__,
    summary="Local-first verified context and change-impact layer.",
)


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness probe. Real routes arrive in Phase 7."""
    return {"status": "ok", "version": __version__}

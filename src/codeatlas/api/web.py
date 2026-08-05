"""Serving the built web application from the API process.

In development the browser talks to Vite, which proxies `/v1` to the API. A
packaged build has no Vite, so the API serves the built assets itself. Either
way the browser sees **one origin**, which is what lets the API keep its
no-CORS, loopback-only posture (ADR-0006 decision 9) rather than relaxing it for
the packaged case.

Two rules shape the routing, and both are easy to get wrong:

* **A client-side route is not a file.** `/conversations/{id}` exists only in the
  browser's router, so a deep link or a reload has to be answered with
  `index.html` and let the router take over.
* **The fallback must not swallow `/v1`.** An unknown API path comes back as the
  contract error envelope with a 404, not as the shell. Returning HTML to a
  client expecting JSON converts a clear failure into a parse error somewhere
  further away from the cause.
"""

from __future__ import annotations

import sys
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

# Everything under this prefix belongs to the API and is never answered with
# the application shell.
_API_PREFIX = "/v1"
_SHELL_CACHE_HEADERS = {
    "Cache-Control": "no-store, max-age=0, must-revalidate",
    "Pragma": "no-cache",
    "Expires": "0",
}

# Where the built assets sit inside a PyInstaller bundle, relative to the
# unpacked data directory.
_BUNDLED_DIRECTORY = "web"


def web_assets_path() -> Path | None:
    """Locate the built web application, or ``None`` if it is not present.

    A frozen build is asked first and answered from ``sys._MEIPASS``: PyInstaller
    unpacks bundled data beside the executable, and a path derived from
    ``__file__`` would point into the archive instead. A source checkout falls
    back to ``apps/web/dist``, which exists only after ``vite build`` — its
    absence is a normal state, not an error.
    """
    if getattr(sys, "frozen", False):
        base = getattr(sys, "_MEIPASS", None)
        if base is None:
            return None
        bundled = Path(base) / _BUNDLED_DIRECTORY
        return bundled if bundled.is_dir() else None

    # src/codeatlas/api/web.py -> repository root
    root = Path(__file__).resolve().parents[3]
    built = root / "apps" / "web" / "dist"
    return built if built.is_dir() else None


def mount_web_application(app: FastAPI, assets: Path) -> None:
    """Serve ``assets`` as the application shell, leaving ``/v1`` untouched.

    Mounted last, after every API router, so no application route can be
    shadowed by a file that happens to share its name.
    """
    index = assets / "index.html"
    if not index.is_file():
        # A packaging mistake must not stop the API from serving. Refusing to
        # boot over a missing SPA would turn a cosmetic error into an outage
        # for the CLI and MCP surfaces too.
        return

    # `StaticFiles` resolves within its directory and rejects traversal, so the
    # arbitrary-path route below never sees a request for a real file.
    app.mount(
        "/assets",
        StaticFiles(directory=assets / "assets", check_dir=False),
        name="assets",
    )

    @app.get("/{full_path:path}", include_in_schema=False)
    async def application_shell(request: Request, full_path: str) -> Response:
        if f"/{full_path}".startswith(_API_PREFIX):
            # Unreachable through normal routing — an API path would have
            # matched its router first — but a request for an *unknown* `/v1`
            # path arrives here. Raising rather than returning a bare 404 sends
            # it through the application's error handler, so it comes back as
            # the contract envelope; returning `Response(404)` here gave the
            # right status with no body, which a client reading `error.code`
            # cannot parse (found in P6-08).
            raise HTTPException(status_code=404)

        candidate = _file_within(assets, full_path)
        if candidate is not None and candidate != index:
            return FileResponse(candidate)

        return _application_shell_response(index)

    _ = application_shell  # registered by decoration; named for the traceback


def _file_within(root: Path, relative: str) -> Path | None:
    """Resolve ``relative`` inside ``root``, or ``None`` if it escapes or misses.

    This is the one route that takes an arbitrary path from the URL, so the
    containment check is explicit rather than assumed: `resolve()` collapses
    `..` and symlinks before the comparison, which is what makes the comparison
    meaningful.
    """
    if not relative:
        return None

    resolved_root = root.resolve()
    try:
        candidate = (resolved_root / relative).resolve()
    except (OSError, ValueError):
        return None

    if not candidate.is_relative_to(resolved_root):
        return None
    return candidate if candidate.is_file() else None


def _application_shell_response(index: Path) -> FileResponse:
    """Return the SPA shell without letting browsers keep an old bundle map.

    Hashed Vite assets can be cached safely, but ``index.html`` is the pointer
    to whichever hashes are current. If a local packaged server is rebuilt
    while a browser tab is open, a cached shell keeps route navigation on the
    old UI until the user manually reloads.
    """
    return FileResponse(index, headers=_SHELL_CACHE_HEADERS)

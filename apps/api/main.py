"""Local REST API entry point.

The server binds to loopback only. Changing `HOST` to a routable address would
expose an unauthenticated service that can read local source, and requires
authentication, a CSRF/CORS review, a revised threat model, and explicit
approval first.
"""

from __future__ import annotations

import uvicorn

from codeatlas.api.app import create_app

HOST = "127.0.0.1"
PORT = 8765


def main() -> None:
    """Run the local API server."""
    uvicorn.run(create_app(), host=HOST, port=PORT, log_level="warning")


if __name__ == "__main__":
    main()

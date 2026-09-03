"""Entry point for the packaged MCP server.

PyInstaller freezes a *script*, not a console-script entry point, so this file
exists to be that script for `codeatlas-mcp.exe`, exactly as `entry.py` does for
`codeatlas.exe`.

It stays deliberately empty of logic, for the same reason `entry.py` does: a
packaged build must answer exactly what a source checkout answers, and any
behavior living only here would be behavior only packaged users get. It calls
the same `main()` the `codeatlas-mcp` console script calls, so the two cannot
drift.

**stdout is the protocol channel.** Nothing here may print, and nothing this
imports may print on import either. A single stray line of output is not a
cosmetic problem: it corrupts the JSON-RPC stream and the client's handshake
fails with no useful error.
"""

from __future__ import annotations

from codeatlas.mcp.server import main

if __name__ == "__main__":
    main()

"""Entry point for the packaged build.

PyInstaller freezes a *script*, not a console-script entry point, so this file
exists to be that script. It stays deliberately empty of logic: a packaged build
must answer exactly what a source checkout answers, and any behavior that lived
only here would be behavior only packaged users get.
"""

from __future__ import annotations

from codeatlas.cli.main import main

if __name__ == "__main__":
    main()

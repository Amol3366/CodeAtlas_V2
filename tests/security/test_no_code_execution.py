"""Security: scanning must never execute repository code (CLAUDE.md §2.4).

The scanner only reads bytes. We prove it by planting files whose *execution*
would leave an observable side effect (a sentinel file, a raised error, a
process exit) and asserting the scan completes cleanly with none of those
effects, while the files themselves are still indexed as evidence.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path

from codeatlas.repositories import path_security as ps
from codeatlas.repositories.scanner import RepositoryScanner
from codeatlas.settings.config import ScanConfig, default_language_index


def test_scanning_does_not_execute_repository_code(
    tmp_path: Path, write_tree: Callable[[Path, Mapping[str, str | bytes]], None]
) -> None:
    sentinel = tmp_path / "SENTINEL_WAS_EXECUTED"
    payload = (
        "from pathlib import Path\n"
        f"Path(r{str(sentinel)!r}).write_text('executed')\n"
        "import sys\n"
        "sys.exit(1)\n"
        "raise SystemExit('should never run')\n"
    )
    write_tree(
        tmp_path,
        {
            "malicious.py": payload,
            "conftest.py": "raise RuntimeError('import side effect')\n",
            "setup.py": "import os; os.system('echo pwned')\n",
        },
    )

    scanner = RepositoryScanner(ScanConfig(), default_language_index())
    result = scanner.scan(ps.normalize_root(tmp_path))

    # No side effects: the payload never ran.
    assert not sentinel.exists()
    # But the files are still indexed as evidence.
    paths = {entry.display_path for entry in result.manifest.entries}
    assert {"malicious.py", "setup.py"} <= paths

"""Resolution of local data directories (CLAUDE.md §3 data locations).

Defaults derive from ``%LOCALAPPDATA%\\CodeAtlas`` on Windows, with a
cross-platform fallback under the user home for development/tests. All values
are overridable via configuration; nothing here creates directories implicitly
except the explicit :func:`ensure_dir` helper.
"""

from __future__ import annotations

import os
from pathlib import Path

_APP_DIR_NAME = "CodeAtlas"


def app_base_dir() -> Path:
    """Base directory for all CodeAtlas local data."""
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / _APP_DIR_NAME
    return Path.home() / f".{_APP_DIR_NAME.lower()}"


def default_data_dir() -> Path:
    return app_base_dir() / "data"


def default_vectors_dir() -> Path:
    return app_base_dir() / "vectors"


def default_cache_dir() -> Path:
    return app_base_dir() / "cache"


def default_database_path() -> Path:
    return default_data_dir() / "codeatlas.db"


def ensure_dir(path: Path) -> Path:
    """Create ``path`` (and parents) if missing; return it."""
    path.mkdir(parents=True, exist_ok=True)
    return path

"""Throwaway storage directories for ephemeral sessions.

An ephemeral run gets its own directory holding the database and, because
``build_services`` and ``create_app`` both derive it from the database's parent,
the vector store beside it. Nothing here is repository truth: the directory is
created empty, and losing it costs re-indexing time and nothing else.

The sweeper exists because a crash cannot run the cleanup path. Without it every
killed run leaks a vector tree, which is measured in hundreds of megabytes once
embeddings are enabled.
"""

from __future__ import annotations

import os
import re
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path

from codeatlas.indexing.ownership import process_is_alive

_SESSIONS_DIRECTORY = Path("CodeAtlas") / "sessions"
_TIMESTAMP_FORMAT = "%Y%m%dT%H%M%SZ"
# `<pid>-<utc timestamp>`, with an optional collision suffix. Anything else in
# the directory was not written by this code and is left alone.
_SESSION_NAME = re.compile(r"^(?P<pid>\d+)-(?P<stamp>\d{8}T\d{6}Z)(?:-\d+)?$")

DEFAULT_MAX_AGE = timedelta(hours=24)


def sessions_root() -> Path:
    """Where session directories live.

    Resolved the same way as the default database, but in a sibling directory
    rather than inside the data directory: deleting the whole session tree can
    then never take the user's real database with it.
    """
    local_app_data = os.environ.get("LOCALAPPDATA")
    base = Path(local_app_data) if local_app_data else Path.home() / ".local" / "share"
    return base / _SESSIONS_DIRECTORY


def create_session_directory(
    *, pid: int | None = None, now: datetime | None = None
) -> Path:
    """Create and return an empty directory for one session.

    The name carries the owning pid and the creation time because those are
    exactly what the sweeper needs later, and a directory that describes itself
    needs no index file to be interpreted after a crash.
    """
    owner = os.getpid() if pid is None else pid
    moment = datetime.now(UTC) if now is None else now

    root = sessions_root()
    stamp = moment.strftime(_TIMESTAMP_FORMAT)
    candidate = root / f"{owner}-{stamp}"

    # Two sessions share a pid and a second only in tests and under pid reuse,
    # but colliding would silently join two runs' data. Suffix instead.
    suffix = 1
    while candidate.exists():
        candidate = root / f"{owner}-{stamp}-{suffix}"
        suffix += 1

    candidate.mkdir(parents=True)
    return candidate


def remove_session_directory(path: Path) -> None:
    """Delete a session directory, tolerating one that is already gone."""
    shutil.rmtree(path, ignore_errors=True)


def sweep_stale_sessions(
    root: Path | None = None,
    *,
    now: datetime | None = None,
    max_age: timedelta = DEFAULT_MAX_AGE,
) -> tuple[Path, ...]:
    """Remove session directories no live run can still own.

    Two rules, because neither is sufficient alone. A dead owning process means
    the session is finished. Age catches what liveness cannot: a reused pid can
    make a dead session look alive, the same limitation crash recovery carries
    and documents rather than pretending to solve.
    """
    target = sessions_root() if root is None else root
    moment = datetime.now(UTC) if now is None else now

    try:
        entries = list(target.iterdir())
    except OSError:
        # A missing root is the normal first-run state, not an error.
        return ()

    removed: list[Path] = []
    for entry in entries:
        if not entry.is_dir():
            continue
        matched = _SESSION_NAME.match(entry.name)
        if matched is None:
            continue

        created_at = datetime.strptime(
            matched.group("stamp"), _TIMESTAMP_FORMAT
        ).replace(tzinfo=UTC)
        expired = moment - created_at >= max_age

        if not expired and process_is_alive(int(matched.group("pid"))):
            continue

        remove_session_directory(entry)
        removed.append(entry)

    return tuple(removed)

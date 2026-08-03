# Ephemeral Session Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an opt-in `--ephemeral` serve mode that starts every run with a fresh database, index, and embeddings, while conversation history behaves normally within that run.

**Architecture:** The mode injects one thing — a session-scoped database path under `%LOCALAPPDATA%/CodeAtlas/sessions/<pid>-<timestamp>/`. Everything else falls out for free, because `api/app.py:127` and `cli/main.py:154` already derive the vector directory as `<database>.parent / "vectors"`. Configured repositories are registered synchronously before the server binds, then indexed on one sequential background thread so the server is usable immediately. A sweeper removes session directories left by crashed runs.

**Tech Stack:** Python 3.12, Typer, FastAPI, SQLite, pytest.

## Global Constraints

- **The default path must not change.** No behavior change unless `--ephemeral` or `CODEATLAS_EPHEMERAL=1` is given. The existing persistence and restart tests must pass unmodified — that is the regression boundary.
- Domain logic must not import framework, HTTP, CLI, or UI code (`AGENTS.md` §4.5).
- Adapters are thin: registration/indexing orchestration lives in `application/`, not in `cli/main.py` (`AGENTS.md` §4.5).
- `.env` is read from the project folder only, never the working directory — a repository being indexed must never configure the tool indexing it (`settings/env_file.py` module docstring).
- Type hints throughout; no `Any` in new code. Ruff and strict MyPy must pass.
- No new dependency. Everything here uses the standard library plus what is already installed.
- Session directory age threshold: **24 hours**.
- Never log absolute local paths by default (`AGENTS.md` §17) — the CLI prints them to the user's own terminal, which is not logging, but nothing here writes them to a log file.

---

### Task 1: Session directory lifecycle

**Files:**
- Create: `src/codeatlas/storage/session.py`
- Test: `tests/unit/test_ephemeral_session.py`

**Interfaces:**
- Consumes: `codeatlas.indexing.ownership.process_is_alive(pid: int) -> bool` (existing).
- Produces:
  - `sessions_root() -> Path`
  - `create_session_directory(*, pid: int | None = None, now: datetime | None = None) -> Path`
  - `remove_session_directory(path: Path) -> None`
  - `sweep_stale_sessions(root: Path | None = None, *, now: datetime | None = None, max_age: timedelta = timedelta(hours=24)) -> tuple[Path, ...]`

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_ephemeral_session.py
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from codeatlas.storage.session import (
    create_session_directory,
    remove_session_directory,
    sessions_root,
    sweep_stale_sessions,
)


@pytest.fixture()
def fake_local_app_data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    return tmp_path


def test_sessions_root_sits_under_local_app_data(fake_local_app_data: Path) -> None:
    assert sessions_root() == fake_local_app_data / "CodeAtlas" / "sessions"


def test_create_session_directory_is_empty_and_unique(
    fake_local_app_data: Path,
) -> None:
    now = datetime(2026, 8, 4, 12, 0, 0, tzinfo=timezone.utc)
    first = create_session_directory(pid=111, now=now)
    second = create_session_directory(pid=222, now=now)

    assert first.is_dir()
    assert second.is_dir()
    assert first != second
    assert list(first.iterdir()) == []


def test_create_session_directory_encodes_pid_and_timestamp(
    fake_local_app_data: Path,
) -> None:
    now = datetime(2026, 8, 4, 12, 30, 45, tzinfo=timezone.utc)
    created = create_session_directory(pid=4242, now=now)

    assert created.name.startswith("4242-")
    assert "20260804T123045Z" in created.name


def test_remove_session_directory_deletes_contents(
    fake_local_app_data: Path,
) -> None:
    created = create_session_directory(pid=os.getpid())
    (created / "codeatlas.db").write_text("data", encoding="utf-8")
    (created / "vectors").mkdir()

    remove_session_directory(created)

    assert not created.exists()


def test_remove_session_directory_tolerates_a_missing_directory(
    fake_local_app_data: Path,
) -> None:
    # A second shutdown path, or a user who deleted it, must not raise.
    remove_session_directory(sessions_root() / "999-20260804T000000Z")


def test_sweep_removes_sessions_whose_process_is_dead(
    fake_local_app_data: Path,
) -> None:
    now = datetime(2026, 8, 4, 12, 0, 0, tzinfo=timezone.utc)
    dead = create_session_directory(pid=999_999, now=now)
    alive = create_session_directory(pid=os.getpid(), now=now)

    removed = sweep_stale_sessions(now=now)

    assert dead in removed
    assert not dead.exists()
    assert alive.exists()


def test_sweep_removes_a_live_pid_session_once_it_is_too_old(
    fake_local_app_data: Path,
) -> None:
    created_at = datetime(2026, 8, 4, 12, 0, 0, tzinfo=timezone.utc)
    # A reused pid can make a dead session look alive. Age collects it anyway.
    stale = create_session_directory(pid=os.getpid(), now=created_at)

    removed = sweep_stale_sessions(now=created_at + timedelta(hours=25))

    assert stale in removed
    assert not stale.exists()


def test_sweep_ignores_unrecognized_directory_names(
    fake_local_app_data: Path,
) -> None:
    root = sessions_root()
    root.mkdir(parents=True, exist_ok=True)
    foreign = root / "not-a-session"
    foreign.mkdir()

    removed = sweep_stale_sessions(now=datetime.now(timezone.utc))

    assert foreign not in removed
    assert foreign.exists()


def test_sweep_returns_empty_when_the_root_does_not_exist(
    fake_local_app_data: Path,
) -> None:
    assert sweep_stale_sessions(now=datetime.now(timezone.utc)) == ()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/test_ephemeral_session.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'codeatlas.storage.session'`

- [ ] **Step 3: Implement the module**

```python
# src/codeatlas/storage/session.py
"""Throwaway storage directories for ephemeral sessions.

An ephemeral run gets its own directory holding the database and, because
`build_services` and `create_app` both derive it, the vector store beside it.
Nothing here is repository truth: the directory is created empty, and losing it
costs re-indexing time and nothing else.

The sweeper exists because a crash cannot run the cleanup path. Without it every
killed run leaks a vector tree, which is measured in hundreds of megabytes once
embeddings are enabled.
"""

from __future__ import annotations

import os
import re
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

from codeatlas.indexing.ownership import process_is_alive

_SESSIONS_DIRECTORY = Path("CodeAtlas") / "sessions"
_TIMESTAMP_FORMAT = "%Y%m%dT%H%M%SZ"
# `<pid>-<utc timestamp>`. Anything else in the directory was not written by
# this code and is left alone.
_SESSION_NAME = re.compile(r"^(?P<pid>\d+)-(?P<stamp>\d{8}T\d{6}Z)$")

DEFAULT_MAX_AGE = timedelta(hours=24)


def sessions_root() -> Path:
    """Where session directories live.

    Resolved the same way as the default database, so a session sits beside the
    real data directory rather than inside it — deleting the whole tree can
    never take the user's real database with it.
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
    moment = datetime.now(timezone.utc) if now is None else now

    root = sessions_root()
    stamp = moment.strftime(_TIMESTAMP_FORMAT)
    candidate = root / f"{owner}-{stamp}"

    # Two sessions can share a pid and a second only in tests and in pid reuse,
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
    moment = datetime.now(timezone.utc) if now is None else now

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
        ).replace(tzinfo=timezone.utc)
        expired = moment - created_at >= max_age

        if not expired and process_is_alive(int(matched.group("pid"))):
            continue

        remove_session_directory(entry)
        removed.append(entry)

    return tuple(removed)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/test_ephemeral_session.py -v`
Expected: PASS (9 tests)

- [ ] **Step 5: Lint and type-check**

Run: `uv run ruff check src tests && uv run mypy --no-incremental src tests`
Expected: exit 0 for both

- [ ] **Step 6: Commit**

```bash
git add src/codeatlas/storage/session.py tests/unit/test_ephemeral_session.py
git commit -m "feat: add ephemeral session directory lifecycle"
```

---

### Task 2: Configured repository list from `.env`

**Files:**
- Modify: `src/codeatlas/settings/env_file.py` (add the variable constant beside the existing ones near line 35, and the accessor beside `configured_local_model`)
- Test: `tests/unit/test_env_file.py` (append)

**Interfaces:**
- Consumes: the existing private `_text(variable: str) -> str | None` helper in `env_file.py`.
- Produces:
  - `EPHEMERAL_REPOSITORIES_VARIABLE = "CODEATLAS_EPHEMERAL_REPOSITORIES"`
  - `configured_ephemeral_repositories() -> tuple[str, ...]`

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/unit/test_env_file.py
import pytest

from codeatlas.settings.env_file import (
    EPHEMERAL_REPOSITORIES_VARIABLE,
    configured_ephemeral_repositories,
)


def test_ephemeral_repositories_default_to_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(EPHEMERAL_REPOSITORIES_VARIABLE, raising=False)
    assert configured_ephemeral_repositories() == ()


def test_ephemeral_repositories_split_on_semicolons(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        EPHEMERAL_REPOSITORIES_VARIABLE, r"C:\one;C:\two"
    )
    assert configured_ephemeral_repositories() == (r"C:\one", r"C:\two")


def test_ephemeral_repositories_drop_blanks_and_trim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A trailing separator is the most common hand-edit, and must not become an
    # empty path that fails registration with a confusing message.
    monkeypatch.setenv(
        EPHEMERAL_REPOSITORIES_VARIABLE, r"  C:\one ;; C:\two ;  "
    )
    assert configured_ephemeral_repositories() == (r"C:\one", r"C:\two")


def test_ephemeral_repositories_preserve_order_and_duplicates_are_removed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        EPHEMERAL_REPOSITORIES_VARIABLE, r"C:\one;C:\two;C:\one"
    )
    assert configured_ephemeral_repositories() == (r"C:\one", r"C:\two")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/test_env_file.py -v -k ephemeral`
Expected: FAIL — `ImportError: cannot import name 'EPHEMERAL_REPOSITORIES_VARIABLE'`

- [ ] **Step 3: Add the constant**

Add beside the other variable constants in `src/codeatlas/settings/env_file.py`, after `LOCAL_MODEL_VARIABLE`:

```python
# Which repositories an ephemeral session registers and indexes at startup.
# Semicolon-separated absolute paths. This names *what to open*, never whether
# a repository may transmit — that stays in SQLite, per repository.
EPHEMERAL_REPOSITORIES_VARIABLE = "CODEATLAS_EPHEMERAL_REPOSITORIES"
```

- [ ] **Step 4: Add the accessor**

Add after `configured_local_model`:

```python
def configured_ephemeral_repositories() -> tuple[str, ...]:
    """Paths an ephemeral session should register at startup, in order.

    Semicolons separate entries because a Windows path contains a colon and may
    contain spaces, which rules out both of the other obvious separators.
    Blanks are dropped and duplicates removed: a trailing separator is the most
    common hand-edit, and registering the same root twice fails the second time
    with an error that reads like a defect.
    """
    raw = _text(EPHEMERAL_REPOSITORIES_VARIABLE)
    if raw is None:
        return ()

    seen: list[str] = []
    for entry in raw.split(";"):
        candidate = entry.strip()
        if candidate and candidate not in seen:
            seen.append(candidate)
    return tuple(seen)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/test_env_file.py -v`
Expected: PASS (all tests in the file, including the four new ones)

- [ ] **Step 6: Commit**

```bash
git add src/codeatlas/settings/env_file.py tests/unit/test_env_file.py
git commit -m "feat: read the ephemeral repository list from .env"
```

---

### Task 3: Bootstrap — register configured repositories, index in the background

**Files:**
- Create: `src/codeatlas/application/ephemeral_bootstrap.py`
- Test: `tests/integration/test_ephemeral_bootstrap.py`

**Interfaces:**
- Consumes:
  - `services.registration.register(RegisterRepositoryRequest(path=..., display_name=None)) -> Repository` (existing)
  - `services.indexing.index(repository_id: str) -> IndexResult` (existing)
  - `codeatlas.domain.errors.CodeAtlasError` (existing)
- Produces:
  - `@dataclass(frozen=True) class BootstrapOutcome` with fields `registered: tuple[str, ...]` and `failures: tuple[BootstrapFailure, ...]`
  - `@dataclass(frozen=True) class BootstrapFailure` with fields `path: str`, `code: str`, `message: str`
  - `register_repositories(services: ApplicationServices, paths: Sequence[str]) -> BootstrapOutcome`
  - `index_repositories(database_path: Path, repository_ids: Sequence[str]) -> None`

Note on why registration and indexing are separate functions: registration is fast and its failures are worth showing before the server binds; indexing is slow and belongs on a background thread. Splitting them is what lets the caller do exactly that.

- [ ] **Step 1: Write the failing tests**

```python
# tests/integration/test_ephemeral_bootstrap.py
from __future__ import annotations

from pathlib import Path

import pytest

from codeatlas.application.ephemeral_bootstrap import (
    index_repositories,
    register_repositories,
)
from codeatlas.storage.sqlite.connection import connect
from codeatlas.storage.sqlite.upgrade import upgrade_database
from codeatlas.application.container import build_services


@pytest.fixture()
def repository(tmp_path: Path) -> Path:
    root = tmp_path / "sample"
    (root / "src").mkdir(parents=True)
    (root / "src" / "app.py").write_text(
        "def greet(name: str) -> str:\n    return f'hi {name}'\n",
        encoding="utf-8",
    )
    return root


@pytest.fixture()
def database(tmp_path: Path) -> Path:
    path = tmp_path / "session" / "codeatlas.db"
    path.parent.mkdir(parents=True)
    upgrade_database(path)
    return path


def test_register_repositories_registers_each_configured_path(
    database: Path, repository: Path
) -> None:
    with connect(database) as connection:
        outcome = register_repositories(
            build_services(connection), [str(repository)]
        )

    assert len(outcome.registered) == 1
    assert outcome.failures == ()


def test_register_repositories_reports_and_skips_an_unusable_path(
    database: Path, repository: Path, tmp_path: Path
) -> None:
    missing = tmp_path / "does-not-exist"

    with connect(database) as connection:
        outcome = register_repositories(
            build_services(connection), [str(missing), str(repository)]
        )

    # The good path must still be registered: one bad entry cannot block start.
    assert len(outcome.registered) == 1
    assert len(outcome.failures) == 1
    assert outcome.failures[0].path == str(missing)
    assert outcome.failures[0].code


def test_index_repositories_activates_a_snapshot(
    database: Path, repository: Path
) -> None:
    with connect(database) as connection:
        outcome = register_repositories(
            build_services(connection), [str(repository)]
        )
    repository_id = outcome.registered[0]

    index_repositories(database, [repository_id])

    with connect(database) as connection:
        snapshot = build_services(connection).indexing.get_active_snapshot(
            repository_id
        )
    assert snapshot is not None


def test_index_repositories_continues_after_one_failure(
    database: Path, repository: Path
) -> None:
    with connect(database) as connection:
        outcome = register_repositories(
            build_services(connection), [str(repository)]
        )
    good = outcome.registered[0]

    # An unknown id must not stop the repositories behind it from indexing.
    index_repositories(database, ["repo_missing", good])

    with connect(database) as connection:
        snapshot = build_services(connection).indexing.get_active_snapshot(good)
    assert snapshot is not None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/integration/test_ephemeral_bootstrap.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'codeatlas.application.ephemeral_bootstrap'`

- [ ] **Step 3: Implement the module**

```python
# src/codeatlas/application/ephemeral_bootstrap.py
"""Opening an ephemeral session on the repositories it was configured with.

An ephemeral session starts empty by design, so without this the user meets an
application with nothing in it and has to re-register by hand every run.

Registration and indexing are deliberately separate. Registration is fast, and
its failures — a path that does not exist, is not a repository, or escapes its
root — are worth reporting before the server binds. Indexing is slow, so it runs
on a background thread and reports progress the way every other index does,
through the existing job and status surfaces. Blocking the bind on it would make
the application look hung on its first run against a large repository.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from codeatlas.application.container import ApplicationServices, build_services
from codeatlas.application.registration import RegisterRepositoryRequest
from codeatlas.domain.errors import CodeAtlasError
from codeatlas.semantic.vector_store import LazyVectorStore
from codeatlas.storage.sqlite.connection import connect


@dataclass(frozen=True)
class BootstrapFailure:
    """One configured path that could not be registered, and why."""

    path: str
    code: str
    message: str


@dataclass(frozen=True)
class BootstrapOutcome:
    """What opening the session actually managed to do."""

    registered: tuple[str, ...]
    failures: tuple[BootstrapFailure, ...]


def register_repositories(
    services: ApplicationServices, paths: Sequence[str]
) -> BootstrapOutcome:
    """Register each configured path, skipping and reporting the ones that fail.

    One unusable entry must not stop the session from starting. A stale path in
    a config file is a normal state, and refusing to serve over it would make
    the whole mode fragile for no gain.
    """
    registered: list[str] = []
    failures: list[BootstrapFailure] = []

    for path in paths:
        try:
            repository = services.registration.register(
                RegisterRepositoryRequest(path=path, display_name=None)
            )
        except CodeAtlasError as error:
            failures.append(
                BootstrapFailure(
                    path=path, code=error.code.value, message=error.message
                )
            )
            continue
        registered.append(repository.repository_id)

    return BootstrapOutcome(
        registered=tuple(registered), failures=tuple(failures)
    )


def index_repositories(
    database_path: Path, repository_ids: Sequence[str]
) -> None:
    """Index each repository in turn, against its own short-lived connection.

    Sequential on purpose. SQLite takes one writer, and indexing several
    repositories at once would serialize on the write lock anyway while making
    the progress reporting harder to read.

    A failure on one repository is contained: the ones behind it still index,
    and the failure surfaces through that repository's status rather than by
    taking down the background thread and leaving the rest silently unindexed.
    """
    for repository_id in repository_ids:
        try:
            with connect(database_path) as connection:
                services = build_services(
                    connection,
                    vectors=LazyVectorStore(database_path.parent / "vectors"),
                )
                services.indexing.index(repository_id)
        except CodeAtlasError:
            continue
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/integration/test_ephemeral_bootstrap.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Verify the import path assumptions**

The exact import locations of `Services`, `build_services`, `RegisterRepositoryRequest`, `LazyVectorStore`, and `upgrade_database` must match this repository. If any import fails, correct the import rather than the call — the call sites above are copied from `src/codeatlas/cli/main.py` lines 144-156 and 178-180, which are known good.

Run: `uv run python -c "import codeatlas.application.ephemeral_bootstrap"`
Expected: exit 0, no output

- [ ] **Step 6: Lint and type-check, then commit**

```bash
uv run ruff check src tests && uv run mypy --no-incremental src tests
git add src/codeatlas/application/ephemeral_bootstrap.py tests/integration/test_ephemeral_bootstrap.py
git commit -m "feat: register and index configured repositories for a session"
```

---

### Task 4: Wire `--ephemeral` into `serve`

**Files:**
- Modify: `src/codeatlas/cli/main.py` — the `serve` command at lines 711-791
- Test: `tests/integration/test_ephemeral_serve.py`

**Interfaces:**
- Consumes: everything produced by Tasks 1-3.
- Produces: `codeatlas serve --ephemeral`; env `CODEATLAS_EPHEMERAL=1`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/integration/test_ephemeral_serve.py
from __future__ import annotations

from pathlib import Path

import pytest

from codeatlas.cli.main import _resolve_serve_database


@pytest.fixture()
def fake_local_app_data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    return tmp_path


def test_default_mode_uses_the_real_database(
    fake_local_app_data: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("CODEATLAS_DB_PATH", raising=False)
    resolved, session = _resolve_serve_database(database=None, ephemeral=False)

    assert session is None
    assert resolved.name == "codeatlas.db"
    assert "sessions" not in resolved.parts


def test_ephemeral_mode_uses_a_fresh_session_database(
    fake_local_app_data: Path,
) -> None:
    resolved, session = _resolve_serve_database(database=None, ephemeral=True)

    assert session is not None
    assert resolved == session / "codeatlas.db"
    assert session.is_dir()


def test_two_ephemeral_sessions_do_not_share_a_directory(
    fake_local_app_data: Path,
) -> None:
    first, first_session = _resolve_serve_database(database=None, ephemeral=True)
    second, second_session = _resolve_serve_database(database=None, ephemeral=True)

    assert first != second
    assert first_session != second_session


def test_explicit_database_wins_over_ephemeral(
    fake_local_app_data: Path, tmp_path: Path
) -> None:
    # An explicit --database is a deliberate instruction. Silently ignoring it
    # in favour of a throwaway directory would lose the user's data selection.
    explicit = tmp_path / "chosen.db"
    resolved, session = _resolve_serve_database(database=explicit, ephemeral=True)

    assert resolved == explicit
    assert session is None


def test_ephemeral_env_variable_enables_the_mode(
    fake_local_app_data: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from codeatlas.cli.main import _ephemeral_requested

    monkeypatch.setenv("CODEATLAS_EPHEMERAL", "1")
    assert _ephemeral_requested(flag=False) is True

    monkeypatch.setenv("CODEATLAS_EPHEMERAL", "0")
    assert _ephemeral_requested(flag=False) is False
    assert _ephemeral_requested(flag=True) is True
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/integration/test_ephemeral_serve.py -v`
Expected: FAIL — `ImportError: cannot import name '_resolve_serve_database'`

- [ ] **Step 3: Add the two helpers to `src/codeatlas/cli/main.py`**

Place them just above the `serve` command (before line 711):

```python
_EPHEMERAL_VARIABLE = "CODEATLAS_EPHEMERAL"
_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})


def _ephemeral_requested(*, flag: bool) -> bool:
    """Whether this run should use a throwaway session database."""
    if flag:
        return True
    raw = os.environ.get(_EPHEMERAL_VARIABLE)
    return raw is not None and raw.strip().lower() in _TRUE_VALUES


def _resolve_serve_database(
    *, database: Path | None, ephemeral: bool
) -> tuple[Path, Path | None]:
    """Return the database to serve, and the session directory to clean up.

    An explicit `--database` outranks `--ephemeral`. Naming a database is a
    deliberate instruction, and quietly serving a throwaway one instead would
    discard the user's choice without saying so.
    """
    if database is not None:
        return database, None
    if not ephemeral:
        return default_database_path(), None

    session = create_session_directory()
    return session / "codeatlas.db", session
```

Add the imports at the top of the file, beside the existing ones:

```python
from codeatlas.application.ephemeral_bootstrap import (
    index_repositories,
    register_repositories,
)
from codeatlas.settings.env_file import configured_ephemeral_repositories
from codeatlas.storage.session import (
    create_session_directory,
    remove_session_directory,
    sweep_stale_sessions,
)
```

`Path`, `connect`, `build_services`, `LazyVectorStore`, and `RegisterRepositoryRequest` are already imported in this file (lines 39, 42, 56, 59). **Neither `os` nor `threading` is imported** — add both to the stdlib import block at the top:

```python
import os
import threading
```

- [ ] **Step 4: Run the helper tests to verify they pass**

Run: `uv run pytest tests/integration/test_ephemeral_serve.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Add the `--ephemeral` option to `serve`**

Add the parameter to the `serve` signature after `open_browser`:

```python
    ephemeral: Annotated[
        bool,
        typer.Option(
            "--ephemeral",
            help="Start from empty storage and discard it when the server stops.",
        ),
    ] = False,
```

- [ ] **Step 6: Replace the database resolution and add bootstrap plus cleanup**

Replace line 758 (`resolved = database or default_database_path()`) and the block through `uvicorn.run(...)` with:

```python
    use_ephemeral = _ephemeral_requested(flag=ephemeral)
    if use_ephemeral:
        # Before creating this run's directory, so a crashed predecessor's
        # vectors are reclaimed rather than accumulating one tree per crash.
        sweep_stale_sessions()

    resolved, session_directory = _resolve_serve_database(
        database=database, ephemeral=use_ephemeral
    )

    # Upgrade before listening: a first run must not answer requests against an
    # unmigrated database, and a database from a newer build must stop the
    # server here rather than fail one request at a time.
    try:
        upgrade_database(resolved)
    except CodeAtlasError as error:
        if session_directory is not None:
            remove_session_directory(session_directory)
        _fail(error)
        return

    if session_directory is not None:
        typer.echo("Ephemeral session: storage is empty and will be discarded.")
        _bootstrap_ephemeral_session(resolved)

    application = create_app(resolved, web_assets=assets)
    url = f"http://{host}:{port}"
    typer.echo(
        f"CodeAtlas is listening on {url}"
        + (" — open it in a browser." if web else " (API only).")
    )

    if open_browser:
        # A browser that will not open is not a reason to refuse to serve.
        with contextlib.suppress(OSError):
            webbrowser.open(url)

    try:
        # `access_log=False` for two reasons that happen to agree.
        #
        # It is what `CLAUDE.md` Section 17 asks for: the access log records a
        # request path per request, and this product writes no logs by default.
        #
        # It is also a deadlock this server had. uvicorn writes that line
        # synchronously **on the event-loop thread**. A server launched by a
        # shortcut, a wrapper script, or a test harness usually gets a pipe for
        # stdout that nobody reads; a pipe holds a few kilobytes, and the write
        # that fills it blocks forever. Not one request — every request, with
        # the process alive and nothing in the log to say why (found in P6-08).
        uvicorn.run(application, host=host, port=port, access_log=False)
    finally:
        # Ctrl-C reaches here too, which is the ordinary way this mode ends.
        if session_directory is not None:
            remove_session_directory(session_directory)
```

- [ ] **Step 7: Add the bootstrap helper beside the other serve helpers**

```python
def _bootstrap_ephemeral_session(database_path: Path) -> None:
    """Register the configured repositories, then index them in the background.

    Registration is reported now because a bad path is worth seeing before the
    browser opens. Indexing is not waited on: the server binds immediately and
    the existing status surfaces report real progress, rather than the terminal
    sitting silent through a first full index.
    """
    paths = configured_ephemeral_repositories()
    if not paths:
        return

    with connect(database_path) as connection:
        outcome = register_repositories(
            build_services(
                connection,
                vectors=LazyVectorStore(database_path.parent / "vectors"),
            ),
            paths,
        )

    for failure in outcome.failures:
        typer.echo(f"{failure.code}: {failure.path} — {failure.message}", err=True)

    if not outcome.registered:
        return

    typer.echo(
        f"Indexing {len(outcome.registered)} repository(s) in the background."
    )
    worker = threading.Thread(
        target=index_repositories,
        args=(database_path, outcome.registered),
        name="ephemeral-bootstrap-index",
        daemon=True,
    )
    worker.start()
```

- [ ] **Step 8: Run the full backend suite to prove the default path is unchanged**

Run: `uv run pytest tests -q`
Expected: PASS with no new failures. Pay particular attention to the persistence and restart tests — they must pass **unmodified**. If any test needed a change to pass, stop: the default path was altered, which this plan forbids.

- [ ] **Step 9: Lint and type-check, then commit**

```bash
uv run ruff check src tests && uv run mypy --no-incremental src tests
git add src/codeatlas/cli/main.py tests/integration/test_ephemeral_serve.py
git commit -m "feat: add --ephemeral serve mode"
```

---

### Task 5: End-to-end proof that two runs share nothing

**Files:**
- Test: `tests/end_to_end/test_ephemeral_session_isolation.py`

**Interfaces:**
- Consumes: Tasks 1-4.
- Produces: nothing consumed by later tasks.

This is the task that actually proves the user's request. Everything before it proves a part.

- [ ] **Step 1: Write the test**

```python
# tests/end_to_end/test_ephemeral_session_isolation.py
"""Two ephemeral runs must share no repository, snapshot, or conversation.

The unit tests prove each piece resolves a fresh path. This proves the whole
mode does what was asked: a second run starts empty even though a first run
indexed a repository and held a conversation.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from codeatlas.application.container import build_services
from codeatlas.application.ephemeral_bootstrap import (
    index_repositories,
    register_repositories,
)
from codeatlas.cli.main import _resolve_serve_database
from codeatlas.storage.sqlite.connection import connect
from codeatlas.storage.sqlite.upgrade import upgrade_database


@pytest.fixture()
def fake_local_app_data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "appdata"))
    return tmp_path


@pytest.fixture()
def repository(tmp_path: Path) -> Path:
    root = tmp_path / "sample"
    (root / "src").mkdir(parents=True)
    (root / "src" / "app.py").write_text(
        "def greet(name: str) -> str:\n    return f'hi {name}'\n",
        encoding="utf-8",
    )
    return root


def test_a_second_session_starts_empty(
    fake_local_app_data: Path, repository: Path
) -> None:
    first, first_session = _resolve_serve_database(database=None, ephemeral=True)
    upgrade_database(first)

    with connect(first) as connection:
        outcome = register_repositories(
            build_services(connection), [str(repository)]
        )
    index_repositories(first, outcome.registered)

    with connect(first) as connection:
        assert len(build_services(connection).repositories.list_all()) == 1

    # A new run of the same command.
    second, second_session = _resolve_serve_database(database=None, ephemeral=True)
    upgrade_database(second)

    assert second_session != first_session
    with connect(second) as connection:
        assert build_services(connection).repositories.list_all() == []


def test_a_session_directory_holds_its_own_vectors(
    fake_local_app_data: Path,
) -> None:
    # The vector directory is derived from the database's parent, so a fresh
    # session directory is what makes embeddings fresh too. If this ever stops
    # being true, the mode silently reuses another run's vectors.
    resolved, session = _resolve_serve_database(database=None, ephemeral=True)

    assert session is not None
    assert resolved.parent == session
```

- [ ] **Step 2: Run it**

Run: `uv run pytest tests/end_to_end/test_ephemeral_session_isolation.py -v`
Expected: PASS (2 tests)

- [ ] **Step 3: Commit**

```bash
git add tests/end_to_end/test_ephemeral_session_isolation.py
git commit -m "test: prove two ephemeral sessions share nothing"
```

---

### Task 6: ADR-0013, contract amendment, and documentation

**Files:**
- Create: `docs/adr/0013-ephemeral-session-mode.md`
- Create: `docs/operations/ephemeral-sessions.md`
- Modify: `AGENTS.md` §8.2 — the "Required behavior" list, the `history survives browser restart and backend restart` bullet
- Modify: `docs/adr/README.md` — the ADR index
- Modify: `.env.example` — document `CODEATLAS_EPHEMERAL_REPOSITORIES`
- Modify: `README.md` — one paragraph in the "What works today" section
- Modify: `documentation/memory.md` and `docs/plans/PLAN.md` — required by `documentation/rules.md`

**Interfaces:** none — documentation only.

- [ ] **Step 1: Write ADR-0013**

Follow the structure of `docs/adr/0012-governed-answer-provider-policy.md`. It must record:
- **Context:** the user wants fresh indexing, embeddings, and storage per run; §8.2 and §9 require the opposite by default.
- **Decision:** an opt-in mode injecting a session-scoped database path; the default is unchanged; the real database is never opened in this mode.
- **Consequences:** every ephemeral run pays a full index; a crashed run leaves a directory until swept; the sweeper inherits the known pid-reuse limitation from crash recovery.
- **Rejected:** wiping tables in the real database (irreversible, races the watcher, defeats backup/restore); a full named-profile system (more machinery than the request needs).

- [ ] **Step 2: Amend `AGENTS.md` §8.2**

Change the bullet reading `history survives browser restart and backend restart;` to:

```markdown
- history survives browser restart and backend restart **in default mode**; the
  opt-in ephemeral session mode (ADR-0013) discards storage on exit by
  definition, and is never the default;
```

This edits the release-blocking contract. **The user must approve this amendment** before the task is considered complete — record the approval in the `docs/plans/PLAN.md` handoff entry.

- [ ] **Step 3: Write `docs/operations/ephemeral-sessions.md`**

Follow the tone of `docs/operations/continuous-freshness.md`. Cover: what the mode is for, how to turn it on (both the flag and the variable), where session directories live, how to configure `CODEATLAS_EPHEMERAL_REPOSITORIES`, what happens on a crash, the 24-hour sweep, and the explicit statement that `--database` outranks `--ephemeral`.

- [ ] **Step 4: Update `.env.example`**

```bash
# Repositories an ephemeral session registers and indexes at startup.
# Semicolon-separated absolute paths. Only used with `serve --ephemeral`.
# CODEATLAS_EPHEMERAL_REPOSITORIES=C:\path\to\repo;C:\path\to\other
```

- [ ] **Step 5: Run the full gate**

Run: `powershell -ExecutionPolicy Bypass -File scripts/check_phase7.ps1 -SkipSync -SkipE2E`
Expected: exit 0

Record the actual command, exit code, and output. Do not claim it passed without running it.

- [ ] **Step 6: Append the handoff entry**

Append — never rewrite — an entry to `docs/plans/PLAN.md` following the existing format: agent, transition, outcome, files, contracts, verification with real exit codes, limitations, next. Update `documentation/memory.md` as `documentation/rules.md` requires.

- [ ] **Step 7: Commit**

```bash
git add docs/ AGENTS.md README.md .env.example documentation/
git commit -m "docs: record ADR-0013 and the ephemeral session mode"
```

---

## Verification Summary

| What | Command |
| --- | --- |
| Session lifecycle | `uv run pytest tests/unit/test_ephemeral_session.py -v` |
| Config parsing | `uv run pytest tests/unit/test_env_file.py -v` |
| Bootstrap | `uv run pytest tests/integration/test_ephemeral_bootstrap.py -v` |
| Serve wiring | `uv run pytest tests/integration/test_ephemeral_serve.py -v` |
| Isolation | `uv run pytest tests/end_to_end/test_ephemeral_session_isolation.py -v` |
| **No default-path regression** | `uv run pytest tests -q` |
| Full gate | `powershell -ExecutionPolicy Bypass -File scripts/check_phase7.ps1 -SkipSync -SkipE2E` |

Manual check, once, on Windows:

```powershell
$env:CODEATLAS_EPHEMERAL_REPOSITORIES = "C:\Amol\vibe_coding\CodeAtlas_V2"
uv run codeatlas serve --web --ephemeral --open
```

Expect: an empty application that registers and begins indexing the configured
repository, a conversation that works normally for the run, and — after Ctrl-C
and a second start — an application with no trace of the first run.

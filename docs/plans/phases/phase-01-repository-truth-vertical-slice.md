# Phase 1 — Repository Truth Vertical Slice

Status: `complete`
Gate authority: user
Prerequisites: Phase 0 `complete`; `CLAUDE.md`; the industry blueprint
Activation gate: this plan must be approved by the user before P1-SETUP moves to
`in_progress`. No Phase 1 implementation may begin before that approval.

## Outcome

A local repository can be registered, scanned, Git-state captured, persisted in
SQLite as an activated snapshot with Python symbols, and queried for an exact
Python symbol through the application service, the `/v1` REST API, and the CLI,
returning snapshot-bound evidence that satisfies the Phase 0 contract `1.0`.

## Completion Gate (from `CLAUDE.md` Section 20)

Phase 1 may enter `awaiting_user_approval` only when all of the following hold
with verification evidence recorded in the handoff log:

1. Windows-safe repository registration and scanning work on a real directory.
2. Ignore rules, classification, scan limits, and Git-state capture work,
   including on a directory that is not a Git repository.
3. SQLite migrations plus repository, snapshot, and file models are applied by an
   explicit migration mechanism and covered by migration tests.
4. Python symbol extraction runs through Tree-sitter plus `ast`.
5. Exact symbol lookup returns validated file-and-line evidence.
6. The repository/index status API and a minimal CLI exist and share the same
   application services.
7. Unit, integration, contract, security, and Windows-path tests pass in the
   current environment.
8. The same exact-symbol question answered through the application service, the
   REST API, and the CLI produces the same evidence for the same snapshot.

## Global Constraints

Every task inherits these. Values are exact.

- Python 3.12 (`requires-python = ">=3.12,<3.13"`); `uv` is the only dependency
  and task runner; `uv.lock` is authoritative and installs run `--frozen`.
- Windows 11 is the primary supported environment. Every path rule must hold for
  drive letters, mixed casing, trailing dots/spaces, reserved device names, and
  deep trees.
- Repository content is untrusted data. Indexing MUST NOT import, execute,
  build, install, or evaluate repository code, hooks, scripts, or binaries.
  `ast.parse` is allowed; `exec`, `eval`, `compile(..., "exec")` with execution,
  `importlib`, and `runpy` on repository content are forbidden.
- Git is invoked only through a non-shell argument array (`shell=False`) with an
  explicit timeout.
- All boundary models are Pydantic models derived from
  `src/codeatlas/contracts.py`. Do not fork or redefine contract types.
- Repository-relative paths are validated with the existing
  `RepositoryRelativePath` rule, reused via
  `pydantic.TypeAdapter(RepositoryRelativePath)`. Do not write a second path
  validator.
- Domain modules (`src/codeatlas/domain/`) MUST NOT import FastAPI, Typer,
  `sqlite3`, `subprocess`, `tree_sitter`, or any adapter module.
- Every SQL statement is parameterized. No f-string or `%`-formatted SQL values.
- No embeddings, LLM, provider, MCP adapter, web UI, FTS5, relation graph,
  chunking, or file watcher in Phase 1.
- The API binds to `127.0.0.1` only. No CORS middleware is added in Phase 1.
- Errors returned to adapters use the contract `ErrorEnvelope`. No stack traces,
  absolute local paths, or source excerpts appear in error responses.
- Exactly one task may be `in_progress` or `verifying`.
- Test-first: write the failing test, observe it fail, then implement.

## Non-Goals (explicitly deferred)

| Deferred item | Phase |
| --- | --- |
| Snapshot rollback across many snapshots, chunk identity, FTS5, lexical search | 2 |
| TypeScript/JavaScript parsing, relations, graph traversal, MCP | 3 |
| Diff and change analysis, SARIF, reports | 4 |
| Conversations, streaming, web UI | 5 |
| File watcher, packaging, background job queue | 6 |
| Embeddings, reranking, generation | 7 |
| YAML/`config/*.yaml` configuration loading (Phase 1 uses code defaults, env
  vars, and CLI flags) | 2+ |
| Structured logging/OpenTelemetry instrumentation (Phase 1 emits no logs
  containing repository content and adds no logging framework) | 6 |

## Phase Architecture Decisions

These are fixed for Phase 1 so that tasks written by different agents compose.
Any deviation requires an ADR and user approval.

### Module map

```text
src/codeatlas/
├── domain/
│   ├── __init__.py
│   ├── errors.py          # CodeAtlasError hierarchy and stable error codes
│   ├── ids.py             # stable_hash and all logical/version ID builders
│   ├── paths.py           # canonicalization and containment rules
│   ├── repository.py      # Repository, ScanLimits, FileClassification, FileRecord
│   ├── snapshot.py        # Snapshot, SnapshotState
│   └── symbols.py         # SymbolRecord
├── repositories/
│   ├── __init__.py
│   ├── classification.py  # path/extension -> FileClassification + language
│   ├── git_state.py       # GitAdapter, GitState
│   ├── ignore_rules.py    # built-in, .gitignore, .codeatlasignore, user rules
│   └── scanner.py         # RepositoryScanner, ScanResult, SkippedFile
├── parsing/
│   ├── __init__.py
│   ├── python_parser.py   # PythonParser (ast authoritative + Tree-sitter spans)
│   └── registry.py        # LanguageParser, ParseRequest, ParseResult, registry
├── storage/
│   ├── __init__.py
│   └── sqlite/
│       ├── __init__.py
│       ├── connection.py  # connect(), default_database_path(), pragmas
│       ├── migrations.py  # explicit forward migration runner
│       ├── migrations/
│       │   └── 0001_phase1_repository_truth.sql
│       └── stores.py      # RepositoryStore, SnapshotStore, FileStore,
│                          # SymbolStore, IndexJobStore
├── application/
│   ├── __init__.py
│   ├── container.py       # ApplicationServices wiring used by every adapter
│   ├── indexing.py        # IndexRepositoryService
│   ├── lookup.py          # ExactSymbolLookupService
│   ├── registration.py    # RegisterRepositoryService
│   └── status.py          # RepositoryStatusService
├── api/
│   ├── __init__.py
│   ├── app.py             # create_app()
│   ├── errors.py          # CodeAtlasError -> HTTP status + ErrorEnvelope
│   └── routers/
│       ├── __init__.py
│       ├── query.py
│       └── repositories.py
└── cli/
    ├── __init__.py
    └── main.py            # Typer application

apps/
├── api/main.py            # uvicorn entry point, 127.0.0.1 only
└── cli/main.py            # console entry point
```

### Identity scheme (`domain/ids.py`)

All IDs are lowercase hex prefixed by a type tag. `stable_hash` is
SHA-256 over `"\x1f".join(parts)` encoded UTF-8, truncated to 32 hex characters.

| ID | Inputs |
| --- | --- |
| `repository_id` | `repo_` + `stable_hash(canonical_root_casefolded)` |
| `file_id` | `file_` + `stable_hash(repository_id, relative_path)` |
| `symbol_id` | `sym_` + `stable_hash(repository_id, relative_path, qualified_name, kind)` |
| `symbol_version_id` | `symv_` + `stable_hash(symbol_id, content_hash, parser_bundle_version)` |
| `snapshot_id` | `snap_` + `stable_hash(repository_id, working_tree_fingerprint, parser_bundle_version, index_version)` |
| `evidence_id` | `ev_` + `stable_hash(snapshot_id, file_id, start_line, end_line)` |

Consequences that tasks must preserve and test:

- unchanged source re-indexed with the same parser produces the same
  `snapshot_id`, `symbol_id`, and `symbol_version_id` (idempotency);
- editing a symbol changes `symbol_version_id` but not `symbol_id`;
- upgrading `PARSER_BUNDLE_VERSION` changes `symbol_version_id` and
  `snapshot_id` but not `symbol_id`.

### Version constants

Declared once and imported everywhere:

- `codeatlas.parsing.registry.PARSER_BUNDLE_VERSION = "1.0.0"`
- `codeatlas.application.indexing.INDEX_VERSION = "1.0.0"`
- `codeatlas.storage.sqlite.migrations.SCHEMA_VERSION = 1`

### Snapshot lifecycle used in Phase 1

```text
discovered -> scanning -> parsing -> indexing -> validating -> active
                  |          |          |            |
                  v          v          v            v
                        failed (previous active snapshot is untouched)

active -> superseded (only inside the activation transaction)
```

Only one snapshot per repository may be `active`. Activation happens in a single
`BEGIN IMMEDIATE` transaction that supersedes the previous active snapshot and
activates the new one. Every read query filters on the active snapshot ID.

### Stable error codes (`domain/errors.py`)

| Code | Meaning | HTTP | CLI exit |
| --- | --- | --- | --- |
| `INVALID_REQUEST` | Malformed or out-of-bounds input | 400 | 2 |
| `PATH_NOT_ALLOWED` | Root is missing, not a directory, UNC, or unreadable | 400 | 5 |
| `PATH_OUTSIDE_ROOT` | Resolved target escapes the approved root | 400 | 5 |
| `SCAN_LIMIT_EXCEEDED` | Declared scan limit exceeded | 400 | 5 |
| `REPOSITORY_NOT_FOUND` | Unknown repository ID | 404 | 3 |
| `REPOSITORY_ALREADY_REGISTERED` | Canonical root already registered | 409 | 2 |
| `SNAPSHOT_NOT_READY` | No active snapshot for the repository | 409 | 3 |
| `INDEX_IN_PROGRESS` | A job for this repository is already running | 409 | 3 |
| `UNSUPPORTED_QUERY_MODE` | Query mode not implemented in this phase | 400 | 2 |
| `INTERNAL_ERROR` | Unexpected failure | 500 | 6 |

CLI exit code `0` is success and `4` is a partial or abstained result (for
example, no symbol matched). These belong to the `codeatlas` product CLI and are
independent of the Phase 0 evaluation CLI codes.

### Evidence and derivation rules

- Evidence lines come from the parsed definition range. A definition range
  starts at the first decorator line when decorators exist, otherwise at the
  `def`/`class` line, and ends at the last body line.
- Excerpts are read from disk at query time and are valid only when the file's
  current SHA-256 equals the hash recorded in the active snapshot. On mismatch
  the evidence is dropped, `snapshot.freshness` becomes `stale`, and a warning
  is emitted. Stale evidence is never returned.
- Excerpts are bounded to 200 lines and 8000 characters; truncation adds the
  warning `EVIDENCE_EXCERPT_TRUNCATED`.
- `Evidence.derivation = deterministic` (a syntactic fact about bytes in the
  snapshot). `Claim.derivation = static_resolved` with `confidence = 0.99` (the
  symbol identity is resolved statically and Python permits dynamic
  redefinition). These two fields are never merged.
- When nothing matches, the service abstains: a summary that names the failed
  lookup, `claims = []`, `evidence = []`. It never invents a path or line.

### Dependencies added in Phase 1

Runtime: `tree-sitter`, `tree-sitter-python`, `fastapi`, `uvicorn`, `typer`.
Dev: `httpx` (required by Starlette's `TestClient`).

Latest published versions observed on 2026-07-25 while writing this plan:
`tree-sitter 0.26.0`, `tree-sitter-python 0.25.0`, `fastapi 0.140.0`,
`uvicorn 0.51.0`, `typer 0.27.0`, `httpx 0.28.1`. P1-SETUP resolves and locks the
actual versions and records them in its handoff; do not hand-edit `uv.lock`.

## Task Board

| Task     | Deliverable                                            | Dependencies | Status    |
| -------- | ------------------------------------------------------ | ------------ | --------- |
| P1-SETUP | Phase activation, dependencies, ADR-0002, tooling       | Phase 0      | `complete` |
| P1-01    | Path safety and repository identity domain              | P1-SETUP     | `complete` |
| P1-02    | Ignore rules, classification, limits, scanner           | P1-01        | `complete` |
| P1-03    | Git state adapter                                       | P1-01        | `complete` |
| P1-04    | SQLite connection, migrations, stores                   | P1-01        | `complete` |
| P1-05    | Parser registry and Python parser                       | P1-02        | `complete` |
| P1-06    | Indexing service, validation, atomic activation         | P1-03, P1-04, P1-05 | `complete` |
| P1-07    | Exact symbol lookup, status, and diagnostics services   | P1-06        | `complete` |
| P1-08    | `/v1` REST adapter                                      | P1-07        | `complete` |
| P1-09    | Minimal CLI adapter                                     | P1-07        | `complete` |
| P1-10    | Security/Windows sweep, baseline, docs, phase gate      | P1-08, P1-09 | `complete` |

---

## P1-SETUP — Phase Activation, Dependencies, and Tooling

**Files**

- Modify: `pyproject.toml`
- Modify: `uv.lock` (regenerated by `uv add`, never hand-edited)
- Create: `docs/adr/0002-phase1-storage-and-migration-mechanism.md`
- Create: `src/codeatlas/domain/__init__.py`, `src/codeatlas/repositories/__init__.py`,
  `src/codeatlas/parsing/__init__.py`, `src/codeatlas/storage/__init__.py`,
  `src/codeatlas/storage/sqlite/__init__.py`,
  `src/codeatlas/application/__init__.py`, `src/codeatlas/api/__init__.py`,
  `src/codeatlas/api/routers/__init__.py`, `src/codeatlas/cli/__init__.py`,
  `apps/__init__.py`, `apps/api/__init__.py`, `apps/cli/__init__.py`
- Create: `tests/unit/__init__.py` is **not** required; pytest uses rootdir
  discovery. Create the directories `tests/unit/`, `tests/integration/`,
  `tests/security/`, `tests/end_to_end/` when their first test is added.

**Steps**

- [ ] **Step 1: Record the plan-approval precondition.** Confirm the user has
  approved this phase plan and that `docs/plans/PLAN.md` lists P1-SETUP as the
  active task. If not, stop and report.

- [ ] **Step 2: Add runtime dependencies.**

```powershell
uv add "tree-sitter>=0.25,<0.27" "tree-sitter-python>=0.25,<0.26" "fastapi>=0.140,<1" "uvicorn>=0.51,<1" "typer>=0.27,<1"
uv add --group dev "httpx>=0.28,<1"
```

If the resolver cannot satisfy a pair, widen only the upper bound of the failing
constraint, rerun, and record the reason in the handoff. Do not remove lower
bounds and do not drop `--frozen` from later sync commands.

- [ ] **Step 3: Verify the parser bundle loads without executing repository
  code.**

```powershell
uv run python -c "import tree_sitter, tree_sitter_python; from tree_sitter import Language, Parser; p = Parser(Language(tree_sitter_python.language())); print(p.parse(b'def f():\n    return 1\n').root_node.sexp()[:40])"
```

Expected: a non-empty S-expression beginning with `(module`.

- [ ] **Step 4: Extend the tooling configuration.** In `pyproject.toml`:

```toml
[project.scripts]
codeatlas = "codeatlas.cli.main:main"

[tool.mypy]
python_version = "3.12"
strict = true
files = ["src", "tests", "scripts", "apps"]
exclude = ["tests/evaluation/cases/fixtures/"]
```

Add `"."` to `pythonpath` so `tests/security/test_api_exposure.py` can import
`apps.api.main`; keep every other pytest option unchanged:

```toml
[tool.pytest.ini_options]
addopts = "-ra -p no:cacheprovider --basetemp=.test-tmp"
pythonpath = ["src", "."]
testpaths = ["tests"]
norecursedirs = ["tests/evaluation/cases/fixtures"]
```

Add `apps` to the Ruff invocation used in scripts and documentation.

- [ ] **Step 5: Create the package skeleton.** Each new `__init__.py` contains
  only a one-line module docstring. No re-exports, no logic.

- [ ] **Step 6: Write ADR-0002.** Follow `docs/adr/0000-template.md`. Decide and
  record:
  1. SQLite with an explicit, forward-only, numbered SQL migration runner
     (`0001_phase1_repository_truth.sql`) instead of Alembic, because Phase 1 has
     one local single-writer database and no ORM; revisit if migrations gain
     branching or data backfill needs.
  2. Database location `%LOCALAPPDATA%\CodeAtlas\data\codeatlas.db`, overridable
     by `CODEATLAS_DB_PATH` and by the CLI `--db` flag.
  3. Pragmas `journal_mode=WAL`, `foreign_keys=ON`, `synchronous=NORMAL`,
     `busy_timeout=5000`.
  4. Phase 1 indexing is synchronous and in-process; no job queue.

- [ ] **Step 7: Verify the workspace is unchanged elsewhere.**

```powershell
uv run pytest -q
uv run ruff check src tests scripts apps
uv run mypy --no-incremental src tests scripts apps
```

Expected: the Phase 0 suite still passes (50 tests at the Phase 0 gate), Ruff and
MyPy clean.

- [ ] **Step 8: Append the handoff** to `docs/plans/PLAN.md` and this file with
  the locked dependency versions, then set P1-01 to `ready`.

**Acceptance**

- New dependencies are locked in `uv.lock` and importable under `--frozen`.
- ADR-0002 exists and is referenced by this plan's handoff.
- The Phase 0 gate still passes.

---

## P1-01 — Path Safety and Repository Identity Domain

**Files**

- Create: `src/codeatlas/domain/errors.py`
- Create: `src/codeatlas/domain/ids.py`
- Create: `src/codeatlas/domain/paths.py`
- Create: `src/codeatlas/domain/repository.py`
- Create: `tests/conftest.py`
- Create: `tests/unit/test_domain_ids.py`
- Create: `tests/security/test_path_safety.py`

**Interfaces produced**

```python
# domain/errors.py
class ErrorCode(StrEnum):
    INVALID_REQUEST = "INVALID_REQUEST"
    PATH_NOT_ALLOWED = "PATH_NOT_ALLOWED"
    PATH_OUTSIDE_ROOT = "PATH_OUTSIDE_ROOT"
    SCAN_LIMIT_EXCEEDED = "SCAN_LIMIT_EXCEEDED"
    REPOSITORY_NOT_FOUND = "REPOSITORY_NOT_FOUND"
    REPOSITORY_ALREADY_REGISTERED = "REPOSITORY_ALREADY_REGISTERED"
    SNAPSHOT_NOT_READY = "SNAPSHOT_NOT_READY"
    INDEX_IN_PROGRESS = "INDEX_IN_PROGRESS"
    UNSUPPORTED_QUERY_MODE = "UNSUPPORTED_QUERY_MODE"
    INTERNAL_ERROR = "INTERNAL_ERROR"

class CodeAtlasError(Exception):
    code: ErrorCode
    retryable: bool
    def __init__(self, message: str, *, details: dict[str, str] | None = None) -> None: ...

class PathSafetyError(CodeAtlasError): ...        # code = PATH_NOT_ALLOWED
class PathOutsideRootError(CodeAtlasError): ...   # code = PATH_OUTSIDE_ROOT
class ScanLimitExceededError(CodeAtlasError): ...
class RepositoryNotFoundError(CodeAtlasError): ...
class RepositoryAlreadyRegisteredError(CodeAtlasError): ...
class SnapshotNotReadyError(CodeAtlasError): ...
class IndexInProgressError(CodeAtlasError): ...
class UnsupportedQueryModeError(CodeAtlasError): ...

# domain/ids.py
def stable_hash(*parts: str) -> str: ...
def repository_id(canonical_root: str) -> str: ...
def file_id(repository_id_value: str, relative_path: str) -> str: ...
def symbol_id(repository_id_value: str, relative_path: str, qualified_name: str, kind: str) -> str: ...
def symbol_version_id(symbol_id_value: str, content_hash: str, parser_bundle_version: str) -> str: ...
def snapshot_id(repository_id_value: str, working_tree_fingerprint: str, parser_bundle_version: str, index_version: str) -> str: ...
def evidence_id(snapshot_id_value: str, file_id_value: str, start_line: int, end_line: int) -> str: ...

# domain/paths.py
def canonicalize_root(raw_path: str) -> Path: ...
def normalize_relative_path(root: Path, target: Path) -> str: ...
def resolve_inside_root(root: Path, relative_path: str) -> Path: ...
def is_inside_root(root: Path, candidate: Path) -> bool: ...

# domain/repository.py
class FileClassification(StrEnum): ...   # 15 members from blueprint 4.3.4
@dataclass(frozen=True)
class ScanLimits:
    max_files: int = 50_000
    max_file_bytes: int = 2_000_000
    max_depth: int = 40
    max_relative_path_length: int = 1024
@dataclass(frozen=True)
class FileRecord:
    file_id: str
    relative_path: str
    display_path: str
    content_hash: str
    size_bytes: int
    line_count: int
    language: str
    classification: FileClassification
@dataclass(frozen=True)
class Repository:
    repository_id: str
    display_name: str
    canonical_root: str
    created_at: datetime
```

**Behavior**

- `canonicalize_root` resolves the path with `Path(raw).resolve(strict=True)`,
  rejects UNC roots (`\\server\share`), non-directories, and missing paths with
  `PathSafetyError`.
- `normalize_relative_path` returns a POSIX, NFC-normalized relative path and
  validates it with `TypeAdapter(RepositoryRelativePath)`; anything rejected by
  the contract raises `PathSafetyError`.
- `is_inside_root` compares `os.path.realpath` of both paths, casefolded on
  Windows, and requires the candidate to be the root or below it. Junction and
  symlink targets outside the root return `False`.
- `resolve_inside_root` raises `PathOutsideRootError` when containment fails.

**Steps**

- [ ] **Step 1: Write the failing ID tests** in `tests/unit/test_domain_ids.py`.

```python
from codeatlas.domain.ids import (
    repository_id, snapshot_id, stable_hash, symbol_id, symbol_version_id,
)


def test_stable_hash_is_deterministic_and_field_separated() -> None:
    assert stable_hash("a", "b") == stable_hash("a", "b")
    assert stable_hash("a", "b") != stable_hash("ab", "")
    assert len(stable_hash("a")) == 32


def test_repository_id_ignores_case_on_the_same_root() -> None:
    assert repository_id("C:/Repos/Demo") == repository_id("c:/repos/demo")


def test_symbol_version_changes_with_content_but_symbol_id_does_not() -> None:
    logical = symbol_id("repo_1", "src/a.py", "A.run", "METHOD")
    first = symbol_version_id(logical, "hash-1", "1.0.0")
    second = symbol_version_id(logical, "hash-2", "1.0.0")
    assert first != second
    assert logical == symbol_id("repo_1", "src/a.py", "A.run", "METHOD")


def test_snapshot_id_is_idempotent_for_identical_inputs() -> None:
    assert snapshot_id("repo_1", "fp", "1.0.0", "1.0.0") == snapshot_id(
        "repo_1", "fp", "1.0.0", "1.0.0"
    )
```

- [ ] **Step 2: Write the failing path-safety tests** in
  `tests/security/test_path_safety.py`.

```python
import os
import subprocess
from pathlib import Path

import pytest

from codeatlas.domain.errors import PathOutsideRootError, PathSafetyError
from codeatlas.domain.paths import (
    canonicalize_root, is_inside_root, normalize_relative_path, resolve_inside_root,
)


def test_canonicalize_root_rejects_missing_directory(tmp_path: Path) -> None:
    with pytest.raises(PathSafetyError):
        canonicalize_root(str(tmp_path / "missing"))


def test_canonicalize_root_rejects_file(tmp_path: Path) -> None:
    target = tmp_path / "file.txt"
    target.write_text("x", encoding="utf-8")
    with pytest.raises(PathSafetyError):
        canonicalize_root(str(target))


def test_normalize_relative_path_rejects_traversal(tmp_path: Path) -> None:
    root = canonicalize_root(str(tmp_path))
    with pytest.raises(PathSafetyError):
        normalize_relative_path(root, root.parent / "outside.py")


def test_resolve_inside_root_rejects_backslash_and_absolute_input(tmp_path: Path) -> None:
    root = canonicalize_root(str(tmp_path))
    for candidate in ("..\\outside.py", "C:/Windows/System32/cmd.exe", "a/../../b.py"):
        with pytest.raises((PathSafetyError, PathOutsideRootError)):
            resolve_inside_root(root, candidate)


def test_junction_or_symlink_escape_is_not_inside_root(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.py").write_text("SECRET = 1\n", encoding="utf-8")
    link = root / "linked"
    if os.name == "nt":
        subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(outside)],
            check=True, capture_output=True, text=True,
        )
    else:
        os.symlink(outside, link, target_is_directory=True)
    assert is_inside_root(canonicalize_root(str(root)), link / "secret.py") is False
```

- [ ] **Step 3: Run both test files and confirm they fail** with
  `ModuleNotFoundError: No module named 'codeatlas.domain.ids'`.

```powershell
uv run pytest tests/unit/test_domain_ids.py tests/security/test_path_safety.py -q
```

- [ ] **Step 4: Implement `errors.py`, `ids.py`, `paths.py`, `repository.py`**
  exactly as specified in the interface block above.

- [ ] **Step 5: Add `tests/conftest.py`** with the shared repository fixture used
  by later tasks.

```python
from collections.abc import Iterator
from pathlib import Path

import pytest


@pytest.fixture()
def sample_repo(tmp_path: Path) -> Iterator[Path]:
    root = tmp_path / "sample_repo"
    (root / "src" / "payments").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "src" / "payments" / "service.py").write_text(
        "from .idempotency import IdempotencyStore\n"
        "\n"
        "class PaymentService:\n"
        "    def __init__(self, store: IdempotencyStore) -> None:\n"
        "        self.store = store\n"
        "\n"
        "    def capture(self, key: str) -> str:\n"
        "        return self.store.claim(key)\n",
        encoding="utf-8",
    )
    (root / "src" / "payments" / "idempotency.py").write_text(
        "class IdempotencyStore:\n"
        "    def claim(self, key: str) -> str:\n"
        "        return key\n",
        encoding="utf-8",
    )
    (root / "README.md").write_text("# Sample\n", encoding="utf-8")
    yield root
```

- [ ] **Step 6: Run the tests and confirm they pass.**

```powershell
uv run pytest tests/unit/test_domain_ids.py tests/security/test_path_safety.py -q
uv run ruff check src tests
uv run mypy --no-incremental src tests
```

- [ ] **Step 7: Append the handoff** and set P1-02 to `ready`.

**Acceptance**

- Traversal, absolute, backslash, UNC, and junction/symlink escapes are rejected.
- ID functions are deterministic and separator-safe.
- No adapter imports appear in `src/codeatlas/domain/`.

---

## P1-02 — Ignore Rules, Classification, Limits, and Scanner

**Files**

- Create: `src/codeatlas/repositories/ignore_rules.py`
- Create: `src/codeatlas/repositories/classification.py`
- Create: `src/codeatlas/repositories/scanner.py`
- Create: `tests/unit/test_ignore_rules.py`
- Create: `tests/unit/test_classification.py`
- Create: `tests/integration/test_scanner.py`

**Interfaces produced**

```python
# repositories/ignore_rules.py
DEFAULT_IGNORE_PATTERNS: tuple[str, ...]   # blueprint 4.3.3 default exclusions
NEVER_IGNORED_BASENAMES: tuple[str, ...]   # lockfiles, Dockerfile, openapi.*, *.sql, CI config

class IgnoreRules:
    @classmethod
    def load(cls, root: Path, user_patterns: Sequence[str] = ()) -> "IgnoreRules": ...
    def is_ignored(self, relative_path: str, *, is_directory: bool) -> bool: ...

# repositories/classification.py
def classify(relative_path: str) -> tuple[FileClassification, str]:
    """Return (classification, language). Language is 'python', 'markdown',
    'json', 'yaml', 'toml', 'typescript', 'javascript', or 'unknown'."""

# repositories/scanner.py
@dataclass(frozen=True)
class SkippedFile:
    relative_path: str
    reason_code: str      # IGNORED | TOO_LARGE | BINARY | UNREADABLE | OUTSIDE_ROOT | PATH_REJECTED

@dataclass(frozen=True)
class ScanResult:
    files: tuple[FileRecord, ...]
    skipped: tuple[SkippedFile, ...]
    warnings: tuple[str, ...]
    working_tree_fingerprint: str

class RepositoryScanner:
    def __init__(self, limits: ScanLimits = ScanLimits()) -> None: ...
    def scan(self, root: Path, rules: IgnoreRules) -> ScanResult: ...
```

**Behavior**

- Ignore precedence: built-in defaults, then `.gitignore`, then
  `.codeatlasignore`, then user patterns. Support only the subset `name`,
  `dir/`, `*.ext`, `prefix*`, and a leading `/` root anchor; a leading `!`
  negation re-includes. Unsupported syntax is skipped with a
  `IGNORE_PATTERN_UNSUPPORTED` warning rather than being misapplied.
- `NEVER_IGNORED_BASENAMES` wins over built-in defaults but not over an explicit
  user or `.codeatlasignore` rule.
- Classification covers all 15 blueprint classes; `tests/**`, `test_*.py`,
  `*_test.py`, `*.spec.ts`, and `*.test.ts` are `TEST_CODE`; `docs/adr/*.md` is
  `ARCHITECTURE_DECISION`; `openapi.*`/`swagger.*` is `API_SPECIFICATION`.
- Binary detection: a NUL byte in the first 8192 bytes, or a decode failure with
  `utf-8` and then `utf-8-sig`. Binary files are skipped with reason `BINARY`.
- Files above `max_file_bytes` are skipped with reason `TOO_LARGE`. Directory
  depth above `max_depth` is skipped. Exceeding `max_files` raises
  `ScanLimitExceededError`.
- `PermissionError` and `OSError` on a file produce `UNREADABLE`, never a crash.
- Traversal order is sorted by relative path so results are deterministic.
- `working_tree_fingerprint` = `stable_hash` over
  `f"{relative_path}:{content_hash}:{size_bytes}"` for included files in sorted
  order.
- `line_count` counts `\n`-terminated lines plus a trailing partial line.
- Directory entries whose resolved target leaves the root are skipped with
  reason `OUTSIDE_ROOT` and warning code `SECURITY_LINK_ESCAPE`.

**Steps**

- [ ] **Step 1: Write failing ignore-rule tests.**

```python
def test_default_patterns_exclude_build_and_vcs_directories(tmp_path: Path) -> None:
    rules = IgnoreRules.load(tmp_path)
    assert rules.is_ignored(".git", is_directory=True) is True
    assert rules.is_ignored("node_modules", is_directory=True) is True
    assert rules.is_ignored("src/app.min.js", is_directory=False) is True
    assert rules.is_ignored("src/app.py", is_directory=False) is False


def test_lockfiles_and_ci_config_are_never_ignored_by_default(tmp_path: Path) -> None:
    rules = IgnoreRules.load(tmp_path)
    assert rules.is_ignored("uv.lock", is_directory=False) is False
    assert rules.is_ignored("Dockerfile", is_directory=False) is False


def test_codeatlasignore_overrides_and_negation_reincludes(tmp_path: Path) -> None:
    (tmp_path / ".codeatlasignore").write_text("docs/\n!docs/keep.md\n", encoding="utf-8")
    rules = IgnoreRules.load(tmp_path)
    assert rules.is_ignored("docs/other.md", is_directory=False) is True
    assert rules.is_ignored("docs/keep.md", is_directory=False) is False
```

- [ ] **Step 2: Write failing classification tests** asserting
  `classify("src/payments/service.py") == (FileClassification.SOURCE_CODE, "python")`,
  `classify("tests/test_service.py") == (FileClassification.TEST_CODE, "python")`,
  `classify("README.md") == (FileClassification.DOCUMENTATION, "markdown")`,
  `classify("uv.lock") == (FileClassification.LOCKFILE, "unknown")`, and
  `classify("docs/adr/0001-x.md") == (FileClassification.ARCHITECTURE_DECISION, "markdown")`.

- [ ] **Step 3: Write failing scanner tests** in
  `tests/integration/test_scanner.py`.

```python
def test_scan_is_deterministic_and_hashes_content(sample_repo: Path) -> None:
    scanner = RepositoryScanner()
    root = canonicalize_root(str(sample_repo))
    first = scanner.scan(root, IgnoreRules.load(root))
    second = scanner.scan(root, IgnoreRules.load(root))
    assert [f.relative_path for f in first.files] == sorted(
        f.relative_path for f in first.files
    )
    assert first.working_tree_fingerprint == second.working_tree_fingerprint


def test_scan_skips_oversized_and_binary_files(sample_repo: Path) -> None:
    (sample_repo / "big.py").write_bytes(b"x" * 3_000_000)
    (sample_repo / "blob.py").write_bytes(b"ok\x00binary")
    root = canonicalize_root(str(sample_repo))
    result = RepositoryScanner().scan(root, IgnoreRules.load(root))
    reasons = {s.relative_path: s.reason_code for s in result.skipped}
    assert reasons["big.py"] == "TOO_LARGE"
    assert reasons["blob.py"] == "BINARY"


def test_scan_raises_when_file_limit_exceeded(sample_repo: Path) -> None:
    root = canonicalize_root(str(sample_repo))
    with pytest.raises(ScanLimitExceededError):
        RepositoryScanner(ScanLimits(max_files=1)).scan(root, IgnoreRules.load(root))


def test_scan_does_not_execute_repository_code(sample_repo: Path) -> None:
    marker = sample_repo / "executed.txt"
    (sample_repo / "sitecustomize.py").write_text(
        f"open(r'{marker}', 'w').write('x')\n", encoding="utf-8"
    )
    root = canonicalize_root(str(sample_repo))
    RepositoryScanner().scan(root, IgnoreRules.load(root))
    assert marker.exists() is False
```

- [ ] **Step 4: Run the three files and confirm import failures.**

```powershell
uv run pytest tests/unit/test_ignore_rules.py tests/unit/test_classification.py tests/integration/test_scanner.py -q
```

- [ ] **Step 5: Implement `ignore_rules.py`, `classification.py`, and
  `scanner.py`** to the behavior above, using `os.scandir` with
  `follow_symlinks=False` and the `domain.paths` helpers for every path decision.

- [ ] **Step 6: Run the tests, Ruff, and MyPy.**

```powershell
uv run pytest tests/unit tests/integration tests/security -q
uv run ruff check src tests
uv run mypy --no-incremental src tests
```

- [ ] **Step 7: Append the handoff** and set P1-03 to `ready`.

**Acceptance**

- Two scans of an unchanged tree produce byte-identical fingerprints.
- Oversized, binary, unreadable, ignored, and escaping entries are skipped with
  a reason code and never crash the scan.
- No repository file is imported or executed.

---

## P1-03 — Git State Adapter

**Files**

- Create: `src/codeatlas/repositories/git_state.py`
- Create: `tests/integration/test_git_state.py`

**Interfaces produced**

```python
GIT_TIMEOUT_SECONDS: float = 10.0

@dataclass(frozen=True)
class GitState:
    is_repository: bool
    head_commit: str | None
    branch: str | None
    is_dirty: bool
    warnings: tuple[str, ...]

class GitAdapter:
    def __init__(self, git_executable: str = "git", timeout_seconds: float = GIT_TIMEOUT_SECONDS) -> None: ...
    def read_state(self, root: Path) -> GitState: ...
```

**Behavior**

- Every invocation uses `subprocess.run([...], shell=False, cwd=str(root),
  capture_output=True, text=True, timeout=self._timeout_seconds,
  env={**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_OPTIONAL_LOCKS": "0"})`.
- Commands, in order: `["git", "rev-parse", "--is-inside-work-tree"]`,
  `["git", "rev-parse", "--verify", "HEAD"]`,
  `["git", "rev-parse", "--abbrev-ref", "HEAD"]`,
  `["git", "status", "--porcelain=v1"]`.
- Never write, fetch, checkout, or run hooks. Never build a command string.
- A directory that is not a Git repository returns
  `GitState(False, None, None, False, ("GIT_NOT_A_REPOSITORY",))` — not an error.
- A missing `git` executable (`FileNotFoundError`) returns
  `GitState(False, None, None, False, ("GIT_EXECUTABLE_UNAVAILABLE",))`.
- A timeout returns `GitState(False, None, None, False, ("GIT_TIMEOUT",))`.
- A repository with no commits (`HEAD` unresolvable) returns
  `head_commit=None` with warning `GIT_NO_COMMITS` and `is_repository=True`.
- `head_commit` is validated as 40 lowercase hex characters before it is
  returned; anything else becomes `None` plus warning `GIT_UNEXPECTED_OUTPUT`.

**Steps**

- [ ] **Step 1: Add the Git repository fixture to `tests/conftest.py`.**

```python
import shutil
import subprocess

requires_git = pytest.mark.skipif(shutil.which("git") is None, reason="git is unavailable")


@pytest.fixture()
def git_repo(sample_repo: Path) -> Path:
    def run(*args: str) -> None:
        subprocess.run(
            ["git", *args], cwd=sample_repo, check=True, capture_output=True, text=True
        )

    run("init", "--initial-branch", "main")
    run("-c", "user.email=dev@example.invalid", "-c", "user.name=Dev", "add", ".")
    run(
        "-c", "user.email=dev@example.invalid", "-c", "user.name=Dev",
        "commit", "-m", "initial",
    )
    return sample_repo
```

- [ ] **Step 2: Write the failing tests.**

```python
@requires_git
def test_reads_branch_and_head_from_a_real_repository(git_repo: Path) -> None:
    state = GitAdapter().read_state(git_repo)
    assert state.is_repository is True
    assert state.branch == "main"
    assert state.head_commit is not None and len(state.head_commit) == 40
    assert state.is_dirty is False


@requires_git
def test_detects_a_dirty_working_tree(git_repo: Path) -> None:
    (git_repo / "README.md").write_text("# Changed\n", encoding="utf-8")
    assert GitAdapter().read_state(git_repo).is_dirty is True


def test_non_git_directory_is_reported_without_error(sample_repo: Path) -> None:
    state = GitAdapter().read_state(sample_repo)
    assert state.is_repository is False
    assert state.head_commit is None
    assert "GIT_NOT_A_REPOSITORY" in state.warnings


def test_missing_git_executable_degrades(sample_repo: Path) -> None:
    state = GitAdapter(git_executable="git-does-not-exist").read_state(sample_repo)
    assert state.is_repository is False
    assert "GIT_EXECUTABLE_UNAVAILABLE" in state.warnings
```

- [ ] **Step 3: Run and confirm failure.**

```powershell
uv run pytest tests/integration/test_git_state.py -q
```

- [ ] **Step 4: Implement `git_state.py`.** Add a module-level comment stating
  that `shell=True` and string commands are prohibited here.

- [ ] **Step 5: Run tests, Ruff, MyPy.**

- [ ] **Step 6: Append the handoff** and set P1-04 to `ready`.

**Acceptance**

- Git state is read for a real repository, a dirty tree, a non-Git directory, and
  a missing executable, with no shell invocation anywhere in the module.

---

## P1-04 — SQLite Connection, Migrations, and Stores

**Files**

- Create: `src/codeatlas/domain/snapshot.py`
- Create: `src/codeatlas/domain/symbols.py`
- Create: `src/codeatlas/storage/sqlite/connection.py`
- Create: `src/codeatlas/storage/sqlite/migrations.py`
- Create: `src/codeatlas/storage/sqlite/migrations/0001_phase1_repository_truth.sql`
- Create: `src/codeatlas/storage/sqlite/stores.py`
- Create: `tests/integration/test_migrations.py`
- Create: `tests/integration/test_stores.py`

**Interfaces produced**

```python
# storage/sqlite/connection.py
def default_database_path() -> Path: ...        # CODEATLAS_DB_PATH or %LOCALAPPDATA%\CodeAtlas\data\codeatlas.db
@contextmanager
def connect(database_path: Path) -> Iterator[sqlite3.Connection]: ...
@contextmanager
def write_transaction(connection: sqlite3.Connection) -> Iterator[sqlite3.Connection]: ...  # BEGIN IMMEDIATE

# storage/sqlite/migrations.py
SCHEMA_VERSION: int = 1
def apply_migrations(connection: sqlite3.Connection) -> int: ...   # returns applied version
def current_version(connection: sqlite3.Connection) -> int: ...

# storage/sqlite/stores.py
class RepositoryStore:
    def add(self, repository: Repository) -> None: ...
    def get(self, repository_id: str) -> Repository | None: ...
    def get_by_root(self, canonical_root: str) -> Repository | None: ...
    def list_all(self) -> tuple[Repository, ...]: ...
class SnapshotStore:
    def add_staging(self, snapshot: Snapshot) -> None: ...
    def set_state(self, snapshot_id: str, state: SnapshotState) -> None: ...
    def activate(self, snapshot_id: str, activated_at: datetime) -> None: ...
    def get_active(self, repository_id: str) -> Snapshot | None: ...
    def get(self, snapshot_id: str) -> Snapshot | None: ...
class FileStore:
    def add_many(self, snapshot_id: str, files: Sequence[FileRecord]) -> None: ...
    def list_for_snapshot(self, snapshot_id: str) -> tuple[FileRecord, ...]: ...
    def get(self, snapshot_id: str, file_id: str) -> FileRecord | None: ...
class SymbolStore:
    def add_many(self, snapshot_id: str, symbols: Sequence[SymbolRecord]) -> None: ...
    def find_exact(self, snapshot_id: str, query: str, limit: int) -> tuple[SymbolRecord, ...]: ...
    def count_for_snapshot(self, snapshot_id: str) -> int: ...
class IndexJobStore:
    def start(self, job_id: str, repository_id: str, snapshot_id: str) -> None: ...
    def update_stage(self, job_id: str, stage: str, status: str) -> None: ...
    def finish(self, job_id: str, status: str, diagnostics: Sequence[str]) -> None: ...
    def active_job_for(self, repository_id: str) -> str | None: ...
```

Each store takes `connection: sqlite3.Connection` in `__init__`.

**Schema (`0001_phase1_repository_truth.sql`)**

```sql
CREATE TABLE schema_migrations (
    version     INTEGER PRIMARY KEY,
    applied_at  TEXT NOT NULL
);

CREATE TABLE repositories (
    repository_id  TEXT PRIMARY KEY,
    display_name   TEXT NOT NULL,
    canonical_root TEXT NOT NULL UNIQUE,
    created_at     TEXT NOT NULL
);

CREATE TABLE snapshots (
    snapshot_id              TEXT PRIMARY KEY,
    repository_id            TEXT NOT NULL REFERENCES repositories(repository_id) ON DELETE CASCADE,
    state                    TEXT NOT NULL,
    git_head                 TEXT,
    git_branch               TEXT,
    git_dirty                INTEGER NOT NULL,
    working_tree_fingerprint TEXT NOT NULL,
    file_count               INTEGER NOT NULL,
    parsed_file_count        INTEGER NOT NULL,
    skipped_file_count       INTEGER NOT NULL,
    parse_error_count        INTEGER NOT NULL,
    parser_bundle_version    TEXT NOT NULL,
    index_version            TEXT NOT NULL,
    created_at               TEXT NOT NULL,
    activated_at             TEXT
);
CREATE UNIQUE INDEX snapshots_one_active_per_repository
    ON snapshots(repository_id) WHERE state = 'active';
CREATE INDEX snapshots_by_repository ON snapshots(repository_id, state);

CREATE TABLE files (
    snapshot_id    TEXT NOT NULL REFERENCES snapshots(snapshot_id) ON DELETE CASCADE,
    file_id        TEXT NOT NULL,
    relative_path  TEXT NOT NULL,
    display_path   TEXT NOT NULL,
    content_hash   TEXT NOT NULL,
    size_bytes     INTEGER NOT NULL,
    line_count     INTEGER NOT NULL,
    language       TEXT NOT NULL,
    classification TEXT NOT NULL,
    PRIMARY KEY (snapshot_id, file_id)
);
CREATE INDEX files_by_path ON files(snapshot_id, relative_path);

CREATE TABLE symbols (
    snapshot_id       TEXT NOT NULL REFERENCES snapshots(snapshot_id) ON DELETE CASCADE,
    symbol_id         TEXT NOT NULL,
    symbol_version_id TEXT NOT NULL,
    file_id           TEXT NOT NULL,
    kind              TEXT NOT NULL,
    name              TEXT NOT NULL,
    qualified_name    TEXT NOT NULL,
    module_path       TEXT NOT NULL,
    signature         TEXT,
    start_line        INTEGER NOT NULL,
    end_line          INTEGER NOT NULL,
    start_byte        INTEGER NOT NULL,
    end_byte          INTEGER NOT NULL,
    content_hash      TEXT NOT NULL,
    visibility        TEXT NOT NULL,
    PRIMARY KEY (snapshot_id, symbol_id),
    FOREIGN KEY (snapshot_id, file_id) REFERENCES files(snapshot_id, file_id) ON DELETE CASCADE
);
CREATE INDEX symbols_by_name ON symbols(snapshot_id, name);
CREATE INDEX symbols_by_qualified_name ON symbols(snapshot_id, qualified_name);

CREATE TABLE index_jobs (
    job_id        TEXT PRIMARY KEY,
    repository_id TEXT NOT NULL REFERENCES repositories(repository_id) ON DELETE CASCADE,
    snapshot_id   TEXT NOT NULL,
    stage         TEXT NOT NULL,
    status        TEXT NOT NULL,
    attempts      INTEGER NOT NULL DEFAULT 1,
    started_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL,
    diagnostics   TEXT NOT NULL DEFAULT '[]'
);
CREATE INDEX index_jobs_by_repository ON index_jobs(repository_id, status);
```

**Behavior**

- `connect` applies `PRAGMA journal_mode=WAL`, `PRAGMA foreign_keys=ON`,
  `PRAGMA synchronous=NORMAL`, `PRAGMA busy_timeout=5000`, sets
  `isolation_level=None`, and creates parent directories.
- `apply_migrations` reads `migrations/*.sql` in sorted numeric order, applies
  only versions above `current_version`, and records each in
  `schema_migrations` inside one transaction per file. Re-running is a no-op.
- Timestamps are stored as ISO-8601 UTC strings with a `Z`-equivalent offset and
  parsed back to timezone-aware `datetime`.
- Every query uses `?` placeholders. `SymbolStore.find_exact` matches, in order:
  `qualified_name = ?`, then `module_path || '.' || qualified_name = ?`, then
  `name = ?`, then a case-insensitive `name` match, stopping at the first
  non-empty tier and ordering by `relative_path, start_line`.

**Steps**

- [ ] **Step 1: Write failing migration tests.**

```python
def test_migrations_are_idempotent_and_record_version(tmp_path: Path) -> None:
    with connect(tmp_path / "db.sqlite") as connection:
        assert apply_migrations(connection) == SCHEMA_VERSION
        assert apply_migrations(connection) == SCHEMA_VERSION
        assert current_version(connection) == SCHEMA_VERSION


def test_pragmas_are_applied(tmp_path: Path) -> None:
    with connect(tmp_path / "db.sqlite") as connection:
        assert connection.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_only_one_active_snapshot_per_repository_is_allowed(tmp_path: Path) -> None:
    with connect(tmp_path / "db.sqlite") as connection:
        apply_migrations(connection)
        # insert one repository and two snapshots, activate both
        with pytest.raises(sqlite3.IntegrityError):
            ...  # second UPDATE ... SET state='active'


def test_deleting_a_repository_cascades_to_snapshots_files_and_symbols(tmp_path: Path) -> None:
    ...
```

- [ ] **Step 2: Write failing store tests** covering: add/get repository by ID
  and by canonical root; staging snapshot is not returned by `get_active`;
  `activate` makes it active; `find_exact` tier order returns
  `PaymentService.capture` for the queries `"PaymentService.capture"`,
  `"capture"`, and `"CAPTURE"`; `add_many` inserts in one transaction.

- [ ] **Step 3: Run both files and confirm failure.**

```powershell
uv run pytest tests/integration/test_migrations.py tests/integration/test_stores.py -q
```

- [ ] **Step 4: Implement `snapshot.py`, `symbols.py`, `connection.py`,
  `migrations.py`, the SQL file, and `stores.py`.** Ship the SQL file inside the
  wheel by adding to `pyproject.toml`:

```toml
[tool.hatch.build.targets.wheel.force-include]
"src/codeatlas/storage/sqlite/migrations" = "codeatlas/storage/sqlite/migrations"
```

Load it with `importlib.resources.files("codeatlas.storage.sqlite") / "migrations"`.

- [ ] **Step 5: Run tests, Ruff, MyPy.**

- [ ] **Step 6: Append the handoff** and set P1-05 to `ready`.

**Acceptance**

- Migrations apply once, are idempotent, and record their version.
- The partial unique index makes a second active snapshot impossible.
- Foreign keys cascade; no unparameterized SQL exists in the module.

---

## P1-05 — Parser Registry and Python Parser

**Files**

- Create: `src/codeatlas/parsing/registry.py`
- Create: `src/codeatlas/parsing/python_parser.py`
- Create: `tests/unit/test_python_parser.py`
- Create: `tests/security/test_parser_safety.py`

**Interfaces produced**

```python
# parsing/registry.py
PARSER_BUNDLE_VERSION: str = "1.0.0"

@dataclass(frozen=True)
class ParseRequest:
    repository_id: str
    snapshot_id: str
    file_id: str
    relative_path: str
    language: str
    content: bytes

@dataclass(frozen=True)
class ParseDiagnostic:
    code: str            # PARSE_SYNTAX_ERROR | PARSE_DECODE_ERROR | PARSE_TOO_LARGE | PARSE_UNSUPPORTED
    message: str
    start_line: int | None

@dataclass(frozen=True)
class ParseResult:
    parser_name: str
    parser_version: str
    success: bool
    symbols: tuple[SymbolRecord, ...]
    diagnostics: tuple[ParseDiagnostic, ...]

class LanguageParser(Protocol):
    name: str
    version: str
    supported_languages: frozenset[str]
    def parse(self, request: ParseRequest) -> ParseResult: ...

class ParserRegistry:
    def register(self, parser: LanguageParser) -> None: ...
    def parser_for(self, language: str) -> LanguageParser | None: ...

def default_registry() -> ParserRegistry: ...   # registers PythonParser only

# parsing/python_parser.py
class PythonParser:
    name = "python"
    version = PARSER_BUNDLE_VERSION
    supported_languages = frozenset({"python"})
    def parse(self, request: ParseRequest) -> ParseResult: ...
```

**Behavior**

- `ast` is authoritative for structure, qualified names, decorators, docstrings,
  async functions, and test detection. Tree-sitter supplies the byte spans and
  produces the error-tolerant symbol set when `ast.parse` raises `SyntaxError`.
- Both layers must run for every Python file. The Tree-sitter parser instance is
  created once per `PythonParser` instance.
- Extracted symbols and their kinds:
  - module symbol: `SymbolKind.MODULE`, `qualified_name = ""` is forbidden — use
    the module's dotted path; range covers the whole file;
  - `ClassDef` → `CLASS`;
  - module-level `FunctionDef`/`AsyncFunctionDef` → `FUNCTION`;
  - function inside a class → `METHOD`, except `__init__` → `CONSTRUCTOR`;
  - name starting with `test_` in a `TEST_CODE` file → `TEST`;
  - module-level `UPPER_SNAKE = ...` assignment → `CONSTANT`.
- `qualified_name` is the dotted path within the file (`PaymentService.capture`).
  `module_path` is the dotted path derived from the relative path with `.py`
  removed and `/` replaced by `.`, dropping a trailing `.__init__`.
- `visibility` is `"private"` when any dotted part starts with `_`, else
  `"public"`.
- Definition range: starts at the first decorator line when decorators exist,
  otherwise the `def`/`class` line; ends at `end_lineno`. `start_byte`/
  `end_byte` come from the Tree-sitter node covering that range; when no node
  matches, they are computed from the line offsets.
- `content_hash` is SHA-256 of the definition's source bytes.
- Content above 2,000,000 bytes returns `success=False` with `PARSE_TOO_LARGE`
  and no symbols. Undecodable content returns `PARSE_DECODE_ERROR`.
- `SyntaxError` returns `success=False`, one `PARSE_SYNTAX_ERROR` diagnostic with
  the error line, and whatever symbols Tree-sitter recovered.
- The module MUST NOT call `exec`, `eval`, `compile` with `"exec"` execution,
  `importlib`, `__import__`, `runpy`, or `subprocess`.

**Steps**

- [ ] **Step 1: Write the failing parser tests.**

```python
SERVICE_SOURCE = (
    b"from .idempotency import IdempotencyStore\n"
    b"\n"
    b"class PaymentService:\n"
    b"    def __init__(self, store: IdempotencyStore) -> None:\n"
    b"        self.store = store\n"
    b"\n"
    b"    def capture(self, key: str) -> str:\n"
    b"        return self.store.claim(key)\n"
)


def _request(content: bytes, path: str = "src/payments/service.py") -> ParseRequest:
    return ParseRequest("repo_1", "snap_1", "file_1", path, "python", content)


def test_extracts_class_method_and_constructor_with_exact_lines() -> None:
    result = PythonParser().parse(_request(SERVICE_SOURCE))
    by_name = {s.qualified_name: s for s in result.symbols}
    assert result.success is True
    assert by_name["PaymentService"].kind is SymbolKind.CLASS
    assert (by_name["PaymentService"].start_line, by_name["PaymentService"].end_line) == (3, 8)
    assert by_name["PaymentService.capture"].kind is SymbolKind.METHOD
    assert (by_name["PaymentService.capture"].start_line, by_name["PaymentService.capture"].end_line) == (7, 8)
    assert by_name["PaymentService.__init__"].kind is SymbolKind.CONSTRUCTOR


def test_module_path_is_derived_from_the_relative_path() -> None:
    result = PythonParser().parse(_request(SERVICE_SOURCE))
    module = next(s for s in result.symbols if s.kind is SymbolKind.MODULE)
    assert module.module_path == "src.payments.service"


def test_decorated_function_range_starts_at_the_decorator() -> None:
    source = b"import functools\n\n@functools.cache\ndef load() -> int:\n    return 1\n"
    result = PythonParser().parse(_request(source, "src/util.py"))
    load = next(s for s in result.symbols if s.qualified_name == "load")
    assert (load.start_line, load.end_line) == (3, 5)


def test_symbol_ids_are_stable_across_repeated_parses() -> None:
    first = PythonParser().parse(_request(SERVICE_SOURCE))
    second = PythonParser().parse(_request(SERVICE_SOURCE))
    assert [s.symbol_id for s in first.symbols] == [s.symbol_id for s in second.symbols]
    assert [s.symbol_version_id for s in first.symbols] == [
        s.symbol_version_id for s in second.symbols
    ]


def test_malformed_source_yields_diagnostics_not_an_exception() -> None:
    result = PythonParser().parse(_request(b"def broken(:\n    pass\n", "src/bad.py"))
    assert result.success is False
    assert any(d.code == "PARSE_SYNTAX_ERROR" for d in result.diagnostics)
```

- [ ] **Step 2: Write the failing safety test** in
  `tests/security/test_parser_safety.py`.

```python
def test_parser_never_executes_module_level_code(tmp_path: Path) -> None:
    marker = tmp_path / "executed.txt"
    source = f"open(r'{marker}', 'w').write('x')\n".encode()
    PythonParser().parse(_request(source, "src/evil.py"))
    assert marker.exists() is False


def test_parser_module_contains_no_execution_primitives() -> None:
    from codeatlas.parsing import python_parser

    text = Path(python_parser.__file__).read_text(encoding="utf-8")
    for forbidden in ("exec(", "eval(", "importlib", "__import__", "runpy", "subprocess"):
        assert forbidden not in text
```

- [ ] **Step 3: Run and confirm failure.**

```powershell
uv run pytest tests/unit/test_python_parser.py tests/security/test_parser_safety.py -q
```

- [ ] **Step 4: Implement `registry.py` then `python_parser.py`.**

- [ ] **Step 5: Run the tests, Ruff, and MyPy.** `tree_sitter_python` ships no
  type stubs; if MyPy reports a missing-stub error, add a narrow override rather
  than weakening `strict`:

```toml
[[tool.mypy.overrides]]
module = ["tree_sitter_python"]
ignore_missing_imports = true
```

- [ ] **Step 6: Append the handoff** and set P1-06 to `ready`.

**Acceptance**

- Line ranges match the assertions above exactly.
- Repeated parses produce identical symbol and version IDs.
- Malformed input produces diagnostics; nothing is executed or imported.

---

## P1-06 — Indexing Service, Validation, and Atomic Activation

**Files**

- Create: `src/codeatlas/application/registration.py`
- Create: `src/codeatlas/application/indexing.py`
- Create: `src/codeatlas/application/container.py`
- Create: `tests/integration/test_indexing.py`

**Interfaces produced**

```python
# application/registration.py
@dataclass(frozen=True)
class RegisterRepositoryRequest:
    path: str
    display_name: str | None = None

class RegisterRepositoryService:
    def __init__(self, repositories: RepositoryStore, clock: Callable[[], datetime]) -> None: ...
    def register(self, request: RegisterRepositoryRequest) -> Repository: ...
    def get(self, repository_id: str) -> Repository: ...       # raises RepositoryNotFoundError
    def list_all(self) -> tuple[Repository, ...]: ...

# application/indexing.py
INDEX_VERSION: str = "1.0.0"

@dataclass(frozen=True)
class IndexResult:
    job_id: str
    snapshot: Snapshot
    warnings: tuple[str, ...]
    skipped: tuple[SkippedFile, ...]
    diagnostics: tuple[ParseDiagnostic, ...]

class IndexRepositoryService:
    def __init__(
        self,
        repositories: RepositoryStore,
        snapshots: SnapshotStore,
        files: FileStore,
        symbols: SymbolStore,
        jobs: IndexJobStore,
        scanner: RepositoryScanner,
        git: GitAdapter,
        registry: ParserRegistry,
        connection: sqlite3.Connection,
        clock: Callable[[], datetime],
        limits: ScanLimits = ScanLimits(),
    ) -> None: ...
    def index(self, repository_id: str) -> IndexResult: ...

class SnapshotValidationError(CodeAtlasError): ...   # code = INTERNAL_ERROR

# application/container.py
@dataclass(frozen=True)
class ApplicationServices:
    registration: RegisterRepositoryService
    indexing: IndexRepositoryService
    lookup: "ExactSymbolLookupService"
    status: "RepositoryStatusService"

def build_services(connection: sqlite3.Connection) -> ApplicationServices: ...
```

**Behavior**

- `register` canonicalizes the root, computes the repository ID, rejects an
  already-registered canonical root with `RepositoryAlreadyRegisteredError`, and
  defaults `display_name` to the root's final component.
- `index` sequence: create the job (`IndexInProgressError` if one is running for
  this repository) → `scanning` → `RepositoryScanner.scan` → `GitAdapter.read_state`
  → compute `snapshot_id` → if that snapshot is already `active`, finish the job
  as `skipped_unchanged` and return it unchanged (idempotency) → insert the
  snapshot in state `parsing` → parse every file whose language has a registered
  parser → `indexing`: insert files and symbols → `validating` → activate.
- Pre-activation validation, all of which must pass:
  1. every `files` row belongs to the new snapshot;
  2. every `symbols` row references a `files` row in the same snapshot;
  3. `1 <= start_line <= end_line <= files.line_count` for every symbol;
  4. `file_count` equals the scan's included-file count;
  5. every `relative_path` passes `TypeAdapter(RepositoryRelativePath)`;
  6. `parser_bundle_version` and `index_version` are non-empty.
  Any failure sets the snapshot to `failed`, records diagnostics on the job, and
  raises `SnapshotValidationError` without touching the previous active snapshot.
- Activation runs inside one `write_transaction`: supersede the previous active
  snapshot, set the new one to `active`, set `activated_at`.
- Files with no registered parser are counted as skipped-for-parsing, not as
  errors. `parse_error_count` counts files whose `ParseResult.success` is `False`.

**Steps**

- [ ] **Step 1: Write the failing integration tests.**

```python
def test_register_then_index_activates_a_snapshot_with_symbols(sample_repo: Path, tmp_path: Path) -> None:
    services = _services(tmp_path)
    repository = services.registration.register(RegisterRepositoryRequest(str(sample_repo)))
    result = services.indexing.index(repository.repository_id)
    assert result.snapshot.state is SnapshotState.ACTIVE
    assert result.snapshot.parsed_file_count == 2
    assert result.snapshot.file_count == 3


def test_reindexing_unchanged_source_is_idempotent(sample_repo: Path, tmp_path: Path) -> None:
    services = _services(tmp_path)
    repository = services.registration.register(RegisterRepositoryRequest(str(sample_repo)))
    first = services.indexing.index(repository.repository_id)
    second = services.indexing.index(repository.repository_id)
    assert first.snapshot.snapshot_id == second.snapshot.snapshot_id


def test_editing_a_symbol_creates_a_new_snapshot_and_supersedes_the_old_one(sample_repo: Path, tmp_path: Path) -> None:
    services = _services(tmp_path)
    repository = services.registration.register(RegisterRepositoryRequest(str(sample_repo)))
    first = services.indexing.index(repository.repository_id)
    path = sample_repo / "src" / "payments" / "service.py"
    path.write_text(path.read_text(encoding="utf-8") + "\n    def refund(self) -> None:\n        return None\n", encoding="utf-8")
    second = services.indexing.index(repository.repository_id)
    assert second.snapshot.snapshot_id != first.snapshot.snapshot_id
    assert second.snapshot.state is SnapshotState.ACTIVE


def test_failed_validation_preserves_the_previous_active_snapshot(sample_repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    services = _services(tmp_path)
    repository = services.registration.register(RegisterRepositoryRequest(str(sample_repo)))
    good = services.indexing.index(repository.repository_id)
    (sample_repo / "extra.py").write_text("VALUE = 1\n", encoding="utf-8")
    monkeypatch.setattr(services.indexing, "_validate_snapshot", _raise_validation_error)
    with pytest.raises(SnapshotValidationError):
        services.indexing.index(repository.repository_id)
    assert services.indexing._snapshots.get_active(repository.repository_id).snapshot_id == good.snapshot.snapshot_id


def test_registering_the_same_root_twice_is_rejected(sample_repo: Path, tmp_path: Path) -> None:
    services = _services(tmp_path)
    services.registration.register(RegisterRepositoryRequest(str(sample_repo)))
    with pytest.raises(RepositoryAlreadyRegisteredError):
        services.registration.register(RegisterRepositoryRequest(str(sample_repo)))


def test_indexing_a_non_git_directory_records_a_warning_and_still_activates(sample_repo: Path, tmp_path: Path) -> None:
    services = _services(tmp_path)
    repository = services.registration.register(RegisterRepositoryRequest(str(sample_repo)))
    result = services.indexing.index(repository.repository_id)
    assert result.snapshot.git_head is None
    assert "GIT_NOT_A_REPOSITORY" in result.warnings
```

Add a `_services(tmp_path)` helper in the test module that opens a connection on
`tmp_path / "db.sqlite"`, applies migrations, and calls `build_services`.

- [ ] **Step 2: Run and confirm failure.**

```powershell
uv run pytest tests/integration/test_indexing.py -q
```

- [ ] **Step 3: Implement `registration.py`, then `indexing.py`, then
  `container.py`.** Keep parsing and Git calls outside the write transaction;
  only the insert batches and the activation use transactions.

- [ ] **Step 4: Run the whole suite, Ruff, and MyPy.**

```powershell
uv run pytest -q
uv run ruff check src tests scripts apps
uv run mypy --no-incremental src tests scripts apps
```

- [ ] **Step 5: Append the handoff** and set P1-07 to `ready`.

**Acceptance**

- Re-indexing unchanged source returns the same snapshot ID and does not create a
  second active snapshot.
- A validation failure leaves the previous active snapshot intact and the failed
  snapshot in state `failed`.
- A non-Git directory indexes successfully with an explicit warning.

---

## P1-07 — Exact Symbol Lookup, Status, and Diagnostics Services

**Files**

- Create: `src/codeatlas/application/lookup.py`
- Create: `src/codeatlas/application/status.py`
- Create: `tests/integration/test_lookup.py`
- Create: `tests/contract/test_query_response_contract.py`

**Interfaces produced**

```python
# application/lookup.py
MAX_QUERY_LENGTH: int = 512
MAX_RESULTS: int = 10
MAX_EXCERPT_LINES: int = 200
MAX_EXCERPT_CHARACTERS: int = 8000

@dataclass(frozen=True)
class SymbolLookupRequest:
    repository_id: str
    query: str
    request_id: str
    max_results: int = MAX_RESULTS

class ExactSymbolLookupService:
    def __init__(
        self,
        repositories: RepositoryStore,
        snapshots: SnapshotStore,
        files: FileStore,
        symbols: SymbolStore,
    ) -> None: ...
    def lookup(self, request: SymbolLookupRequest) -> QueryResponse: ...

# application/status.py
@dataclass(frozen=True)
class RepositoryStatus:
    repository: Repository
    snapshot: SnapshotReference | None
    file_count: int
    symbol_count: int
    parse_error_count: int
    warnings: tuple[str, ...]

@dataclass(frozen=True)
class RepositoryDiagnostics:
    repository_id: str
    snapshot_id: str | None
    skipped_by_reason: dict[str, int]
    parse_error_count: int
    limits: ScanLimits
    warnings: tuple[str, ...]

class RepositoryStatusService:
    def status(self, repository_id: str) -> RepositoryStatus: ...
    def diagnostics(self, repository_id: str) -> RepositoryDiagnostics: ...
```

**Behavior**

- Reject an empty query or one longer than `MAX_QUERY_LENGTH` with
  `CodeAtlasError(INVALID_REQUEST)`; clamp `max_results` to `MAX_RESULTS`.
- Raise `RepositoryNotFoundError` for an unknown repository and
  `SnapshotNotReadyError` when no snapshot is active.
- For each matching symbol: read the file at
  `resolve_inside_root(root, relative_path)`, recompute SHA-256, and compare with
  the snapshot's `files.content_hash`. On mismatch, drop the candidate, add the
  warning `EVIDENCE_STALE_FILE_CONTENT`, and set `SnapshotReference.freshness` to
  `stale`.
- Build `Evidence` with `derivation=deterministic`, `confidence=1.0`,
  `validation=valid`, the bounded excerpt, and the file's `content_hash`.
- Build one `Claim` per symbol: `derivation=static_resolved`, `confidence=0.99`,
  text `"{qualified_name} is defined in {relative_path} lines {start}-{end}."`
- `SnapshotReference`: `git_head` from the snapshot, `working_tree_fingerprint`
  from the snapshot, `freshness=fresh` normally, `semantic_coverage=0.0`.
- `limitations` always includes
  `"Phase 1 resolves Python definitions only; relations, other languages, and semantic retrieval are unavailable."`
- Abstention: summary
  `"CodeAtlas found no indexed symbol matching '{query}' in the active snapshot."`,
  empty claims and evidence, plus the warning `NO_EXACT_SYMBOL_MATCH`.
- `timing_ms` records at least the keys `lookup` and `evidence`.

**Steps**

- [ ] **Step 1: Write the failing lookup tests.**

```python
def test_exact_lookup_returns_validated_snapshot_bound_evidence(indexed: _Indexed) -> None:
    response = indexed.services.lookup.lookup(
        SymbolLookupRequest(indexed.repository_id, "PaymentService.capture", "req-1")
    )
    assert response.contract_version == "1.0"
    assert response.snapshot.snapshot_id == indexed.snapshot_id
    evidence = response.evidence[0]
    assert evidence.file_path == "src/payments/service.py"
    assert (evidence.start_line, evidence.end_line) == (7, 8)
    assert evidence.derivation is Derivation.DETERMINISTIC
    assert response.answer.claims[0].derivation is Derivation.STATIC_RESOLVED
    assert response.answer.claims[0].evidence_ids == [evidence.evidence_id]


def test_bare_name_and_case_insensitive_lookup_resolve(indexed: _Indexed) -> None:
    for query in ("capture", "CAPTURE"):
        response = indexed.services.lookup.lookup(
            SymbolLookupRequest(indexed.repository_id, query, "req-2")
        )
        assert response.evidence[0].symbol == "PaymentService.capture"


def test_unknown_symbol_abstains_without_inventing_evidence(indexed: _Indexed) -> None:
    response = indexed.services.lookup.lookup(
        SymbolLookupRequest(indexed.repository_id, "NoSuchSymbol", "req-3")
    )
    assert response.answer.claims == []
    assert response.evidence == []
    assert "NO_EXACT_SYMBOL_MATCH" in response.warnings


def test_modified_file_after_indexing_is_reported_stale_and_not_cited(indexed: _Indexed) -> None:
    path = indexed.root / "src" / "payments" / "service.py"
    path.write_text("# edited\n" + path.read_text(encoding="utf-8"), encoding="utf-8")
    response = indexed.services.lookup.lookup(
        SymbolLookupRequest(indexed.repository_id, "PaymentService.capture", "req-4")
    )
    assert response.snapshot.freshness is SnapshotFreshness.STALE
    assert response.evidence == []
    assert "EVIDENCE_STALE_FILE_CONTENT" in response.warnings


def test_lookup_without_an_active_snapshot_raises(sample_repo: Path, tmp_path: Path) -> None:
    services = _services(tmp_path)
    repository = services.registration.register(RegisterRepositoryRequest(str(sample_repo)))
    with pytest.raises(SnapshotNotReadyError):
        services.lookup.lookup(SymbolLookupRequest(repository.repository_id, "PaymentService", "req-5"))


def test_overlong_query_is_rejected(indexed: _Indexed) -> None:
    with pytest.raises(CodeAtlasError):
        indexed.services.lookup.lookup(
            SymbolLookupRequest(indexed.repository_id, "x" * 513, "req-6")
        )
```

- [ ] **Step 2: Write the failing contract test** in
  `tests/contract/test_query_response_contract.py`, asserting that the response
  round-trips through `QueryResponse.model_validate_json(response.model_dump_json())`,
  that every claim's evidence IDs resolve, that every evidence item carries the
  response's `repository_id` and `snapshot_id`, and that the excerpt is at most
  `MAX_EXCERPT_CHARACTERS`.

- [ ] **Step 3: Run and confirm failure.**

```powershell
uv run pytest tests/integration/test_lookup.py tests/contract/test_query_response_contract.py -q
```

- [ ] **Step 4: Implement `lookup.py` and `status.py`.**

- [ ] **Step 5: Run tests, Ruff, MyPy.**

- [ ] **Step 6: Append the handoff** and set P1-08 to `ready`.

**Acceptance**

- Every returned response validates against contract `1.0` with valid,
  snapshot-bound evidence.
- Drifted files never produce evidence; the response says so explicitly.
- An unmatched query abstains with no fabricated path, line, or symbol.

---

## P1-08 — `/v1` REST Adapter

**Files**

- Create: `src/codeatlas/api/app.py`
- Create: `src/codeatlas/api/errors.py`
- Create: `src/codeatlas/api/routers/repositories.py`
- Create: `src/codeatlas/api/routers/query.py`
- Create: `apps/api/main.py`
- Create: `tests/contract/test_rest_api.py`
- Create: `tests/security/test_api_exposure.py`

**Endpoints (all under `/v1`)**

| Method | Path | Body / result |
| --- | --- | --- |
| `POST` | `/v1/repositories` | `{"path": str, "display_name": str \| null}` → 201 repository |
| `GET` | `/v1/repositories` | list of repositories |
| `GET` | `/v1/repositories/{repository_id}` | repository or 404 |
| `POST` | `/v1/repositories/{repository_id}/index` | 200 `IndexResult` summary |
| `GET` | `/v1/repositories/{repository_id}/status` | `RepositoryStatus` |
| `GET` | `/v1/repositories/{repository_id}/diagnostics` | `RepositoryDiagnostics` |
| `GET` | `/v1/repositories/{repository_id}/snapshots/active` | `SnapshotReference` or 409 |
| `POST` | `/v1/query` | `{"repository_id": str, "query": str, "mode": "exact_symbol"}` → `QueryResponse` |

**Behavior**

- `create_app(connection_factory: Callable[[], sqlite3.Connection]) -> FastAPI`.
  The connection is opened per request through a dependency; services are built
  with `build_services`. Adapters contain no repository logic.
- Response models are the contract models themselves. Repository/status/index
  responses are new Pydantic models in `api/routers/*.py` that derive their
  fields from the application dataclasses; they never redefine `Evidence`,
  `Claim`, `SnapshotReference`, or `QueryResponse`.
- An exception handler maps `CodeAtlasError` to the status codes in the error
  table and serializes `ErrorEnvelope` with the request's `X-Request-Id` header
  or a generated one. Unhandled exceptions become `INTERNAL_ERROR` with a
  generic message.
- Any `mode` other than `"exact_symbol"` returns 400 `UNSUPPORTED_QUERY_MODE`.
- `apps/api/main.py` exposes `HOST = "127.0.0.1"`, `PORT = 8765`, and a `main()`
  that calls `uvicorn.run(create_app(...), host=HOST, port=PORT)`. No CORS
  middleware is registered.
- `display_path` may be returned to the client; absolute local paths must not
  appear in any error response.

**Steps**

- [ ] **Step 1: Write the failing contract tests** using
  `fastapi.testclient.TestClient` against a temporary database, covering: the
  full register → index → query flow returns 201/200/200; the query response body
  parses with `QueryResponse.model_validate(response.json())`; an unknown
  repository returns 404 with `error.code == "REPOSITORY_NOT_FOUND"`; querying
  before indexing returns 409 `SNAPSHOT_NOT_READY`; `mode="semantic"` returns 400
  `UNSUPPORTED_QUERY_MODE`; and registering a path outside any allowed root
  (`{"path": "C:/Windows"}` on Windows, `{"path": "/etc"}` elsewhere, plus a
  non-existent path) returns 400 with a `PATH_*` code.

- [ ] **Step 2: Write the failing exposure tests** in
  `tests/security/test_api_exposure.py`:

```python
def test_default_bind_host_is_loopback() -> None:
    from apps.api.main import HOST
    assert HOST == "127.0.0.1"


def test_no_cors_middleware_is_registered(client_app: FastAPI) -> None:
    assert all("CORSMiddleware" not in type(m.cls).__name__ for m in client_app.user_middleware)


def test_error_responses_contain_no_absolute_paths_or_tracebacks(client: TestClient, tmp_path: Path) -> None:
    response = client.post("/v1/repositories", json={"path": str(tmp_path / "missing")})
    body = response.text
    assert response.status_code == 400
    assert "Traceback" not in body
    assert str(tmp_path) not in body
```

- [ ] **Step 3: Run and confirm failure.**

```powershell
uv run pytest tests/contract/test_rest_api.py tests/security/test_api_exposure.py -q
```

- [ ] **Step 4: Implement `errors.py`, the routers, `app.py`, and
  `apps/api/main.py`.**

- [ ] **Step 5: Run tests, Ruff, MyPy on `src tests scripts apps`.**

- [ ] **Step 6: Append the handoff** and set P1-09 to `ready`.

**Acceptance**

- The REST flow works end to end and returns contract-valid responses.
- Errors use the contract envelope with stable codes and leak no paths or traces.
- The service binds to loopback and registers no CORS middleware.

---

## P1-09 — Minimal CLI Adapter

**Files**

- Create: `src/codeatlas/cli/main.py`
- Create: `apps/cli/main.py`
- Create: `tests/end_to_end/test_cli.py`

**Commands**

```text
codeatlas repo add <path> [--name NAME] [--db PATH] [--json]
codeatlas repo list [--db PATH] [--json]
codeatlas index <repository_id> [--db PATH] [--json]
codeatlas status <repository_id> [--db PATH] [--json]
codeatlas symbol <repository_id> <query> [--db PATH] [--json] [--limit N]
```

**Behavior**

- `main()` is a Typer application; `--json` prints the same payload the REST
  adapter returns (contract models serialized with `model_dump_json`), and the
  default human output is a compact aligned summary. Both call the same
  `ApplicationServices`; no logic is duplicated.
- `--db` defaults to `default_database_path()`; migrations are applied on
  connect.
- Exit codes follow the phase error table: `0` success, `2` invalid input, `3`
  repository or snapshot unavailable, `4` partial or abstained result, `5` policy
  failure (path safety, scan limits), `6` internal failure.
- Human output never prints an absolute path other than the repository root the
  user supplied; JSON output prints repository-relative paths only.

**Steps**

- [ ] **Step 1: Write the failing CLI tests** with `typer.testing.CliRunner`:

```python
def test_add_index_and_symbol_round_trip_in_json(sample_repo: Path, tmp_path: Path) -> None:
    db = str(tmp_path / "db.sqlite")
    runner = CliRunner()
    added = runner.invoke(app, ["repo", "add", str(sample_repo), "--db", db, "--json"])
    assert added.exit_code == 0
    repository_id = json.loads(added.stdout)["repository_id"]

    indexed = runner.invoke(app, ["index", repository_id, "--db", db, "--json"])
    assert indexed.exit_code == 0

    found = runner.invoke(app, ["symbol", repository_id, "PaymentService.capture", "--db", db, "--json"])
    assert found.exit_code == 0
    response = QueryResponse.model_validate_json(found.stdout)
    assert response.evidence[0].file_path == "src/payments/service.py"


def test_unknown_symbol_exits_with_the_partial_code(sample_repo: Path, tmp_path: Path) -> None:
    ...  # exit_code == 4, empty evidence


def test_unknown_repository_exits_with_the_unavailable_code(tmp_path: Path) -> None:
    ...  # exit_code == 3


def test_invalid_path_exits_with_the_policy_code(tmp_path: Path) -> None:
    ...  # repo add on a missing directory -> exit_code == 5
```

- [ ] **Step 2: Write the cross-adapter agreement test** in the same file: index
  once through the CLI, then query the same symbol through the CLI and through
  `TestClient`, and assert both responses have the same `snapshot.snapshot_id`
  and the same `(file_path, start_line, end_line)` for the first evidence item.

- [ ] **Step 3: Run and confirm failure.**

```powershell
uv run pytest tests/end_to_end/test_cli.py -q
```

- [ ] **Step 4: Implement `src/codeatlas/cli/main.py` and `apps/cli/main.py`.**

- [ ] **Step 5: Verify the installed console script.**

```powershell
uv run codeatlas --help
uv run codeatlas repo add . --db .test-output/manual.sqlite --json
```

- [ ] **Step 6: Run the full suite, Ruff, and MyPy; append the handoff** and set
  P1-10 to `ready`.

**Acceptance**

- All five commands work with and without `--json`.
- Exit codes distinguish invalid input, unavailable repository, partial result,
  policy failure, and internal failure.
- CLI and REST return identical evidence for the same query and snapshot.

---

## P1-10 — Security and Windows Sweep, Baseline, Documentation, Phase Gate

**Files**

- Create: `tests/security/test_windows_paths.py`
- Create: `src/codeatlas/evaluation/engine_adapter.py`
- Create: `scripts/run_phase1_baseline.py`
- Create: `scripts/check_phase1.ps1`
- Create: `docs/evaluation/baseline-phase-1.json`
- Create: `docs/evaluation/baseline-phase-1.md`
- Create: `docs/operations/development-windows-phase1.md`
- Modify: `docs/security/threat-model.md` (Phase 1 control status column)
- Modify: `README.md` (quick start for register/index/query)

**Behavior**

1. **Windows and security sweep.** Add tests for: a repository path with mixed
   casing resolving to the same `repository_id`; a file named `NUL.py` or
   `aux.txt` being skipped with reason `PATH_REJECTED`; a path segment ending in
   a space or dot being rejected; a relative path longer than
   `max_relative_path_length` being skipped; a directory nested deeper than
   `max_depth` being skipped; and a junction pointing outside the root being
   excluded from the scan result. Guard Windows-only assertions with
   `pytest.mark.skipif(os.name != "nt", reason="Windows-only path semantics")`.
2. **Evaluation adapter.** `engine_adapter.py` exposes
   `predict_exact_symbols(dataset_root: Path, fixture: str = "python_app") -> PredictionFile`.
   It registers the fixture directory, indexes it, and answers only cases whose
   `intent == "EXACT_SYMBOL"` and whose `repository_fixture` matches; every other
   case is emitted as abstained with empty rankings. Emitted
   `EvidencePrediction.snapshot_id` uses the dataset case's declared
   `snapshot_id` so predictions align with the gold corpus, while the underlying
   evidence is validated against the engine's own active snapshot first; the
   adapter must refuse to emit any evidence it did not validate.
3. **Honest baseline.** `scripts/run_phase1_baseline.py` writes
   `docs/evaluation/baseline-phase-1.json` and `.md` through the existing
   evaluation runner **without** `--enforce-targets`, because Phase 1 implements
   one intent out of nine. Known corpus/engine granularity mismatches must be
   recorded rather than fixed by editing gold cases: with definition-range
   evidence the fixture cases `q001` (3–11), `q002` (7–11), `q004` (1–9), and
   `q008` (7–9) match, while `q009` expects the narrower range 10–11 for
   `PaymentService.capture`. **Do not modify `tests/evaluation/cases/**` to raise
   a metric.** If a gold case looks wrong, record it as a limitation and request
   user approval.
4. **`scripts/check_phase1.ps1`.** Model it on `scripts/check_phase0.ps1`: frozen
   sync, contract schema freshness, `pytest -q`, `ruff check src tests scripts apps`,
   `mypy --no-incremental src tests scripts apps`, the Phase 0 dataset validation
   and null-baseline `--check`, then the Phase 1 baseline with `--check`. Fail on
   the first non-zero exit code.
5. **Documentation.** Add the Windows Phase 1 workflow document, refresh the
   threat-model rows that Phase 1 now enforces, and give `README.md` the three
   commands that register, index, and query a repository.

**Steps**

- [ ] **Step 1: Write the failing Windows/security tests** described above and
  run them.

```powershell
uv run pytest tests/security -q
```

- [ ] **Step 2: Implement any scanner or path fixes** the sweep exposes, then
  rerun `tests/security` and `tests/integration`.

- [ ] **Step 3: Write `engine_adapter.py` with a test** in
  `tests/evaluation/test_engine_adapter.py` asserting that `q001`, `q002`,
  `q004`, and `q008` resolve their expected symbol, that non-`EXACT_SYMBOL` cases
  are abstained, and that no emitted evidence references a file the engine did
  not index.

- [ ] **Step 4: Generate the Phase 1 baseline.**

```powershell
uv run python scripts/run_phase1_baseline.py --dataset tests/evaluation/cases --json-output docs/evaluation/baseline-phase-1.json --markdown-output docs/evaluation/baseline-phase-1.md
```

Record the actual metric values and the SHA-256 of both artifacts in the handoff.

- [ ] **Step 5: Add `scripts/check_phase1.ps1` and run the complete gate.**

```powershell
powershell -ExecutionPolicy Bypass -File scripts/check_phase1.ps1
```

Expected: exit code 0. Record the test count, timings, and every command.

- [ ] **Step 6: Update the documentation** listed above.

- [ ] **Step 7: Self-review the diff** against the `CLAUDE.md` Section 24
  pull-request checklist. Confirm no unrelated edits, no secrets, no debug code,
  no swallowed exceptions, and no unbounded operations.

- [ ] **Step 8: Move P1-10 to `awaiting_user_approval`** and append the phase
  gate handoff to `docs/plans/PLAN.md` and this file, including: every
  verification command with exit codes, the honest baseline numbers, the recorded
  limitations (`q009` granularity, one implemented intent, no relations, Python
  only), and the exact next decision required from the user. Do not mark Phase 1
  `complete`.

**Acceptance**

- The Windows and security suites pass in the current environment, or any check
  that cannot run is reported with its exact command, exit code, and reason —
  never as passed.
- The Phase 1 baseline is reproducible and honest, with unimplemented intents
  reported as abstained rather than zero-scored inventions.
- `scripts/check_phase1.ps1` exits 0 and is documented.
- Phase 1 sits at `awaiting_user_approval` with the completion-gate evidence
  recorded.

---

## Phase Verification Commands

```powershell
powershell -ExecutionPolicy Bypass -File scripts/setup_windows.ps1
uv run pytest -q
uv run ruff check src tests scripts apps
uv run mypy --no-incremental src tests scripts apps
uv run python scripts/export_contract_schema.py --check
uv run python scripts/run_evaluation.py validate --dataset tests/evaluation/cases
powershell -ExecutionPolicy Bypass -File scripts/check_phase1.ps1 -SkipSync
```

## Known Environment Limitations

- The workspace is a Git repository on branch `main` with no commits yet; all
  files are untracked. Until the first commit exists, handoffs cannot cite a
  commit SHA or diff. Each task's handoff MUST record the commit SHA once one is
  available.
- Git-dependent Phase 1 tests build their own temporary repositories with
  `git init` in `tmp_path` and skip when the `git` executable is unavailable.
  They never depend on CodeAtlas's own history.
- `git version 2.55.0.windows.3` and `uv 0.11.24` were observed in this
  environment on 2026-07-25.
- Local scripts require `powershell -ExecutionPolicy Bypass -File ...`.

## Phase Handoff Log

### 2026-07-25T20:04:24Z — Phase 1 approved and closed

- Agent: Claude Code `claude-opus-5`
- Approval: The user approved the Phase 1 gate and instructed that the work be
  committed.
- Transition: P1-10 `awaiting_user_approval -> complete`; Phase 1
  `awaiting_user_approval -> complete`.
- Verification: Status-only change; no executable tests were run for it. The
  release-gate evidence remains the 2026-07-25T19:59:34Z entry.
- Limitations: unchanged from the gate entry, including the deferred `q009`
  evidence-granularity decision.
- Next: await user instruction before preparing Phase 2.

### 2026-07-25T19:59:34Z — P1-10 completed; Phase 1 awaiting user approval

- Agent: Claude Code `claude-opus-5`
- Transition: P1-10 `in_progress -> awaiting_user_approval`; Phase 1
  `in_progress -> awaiting_user_approval`.
- Outcome: Windows and security sweep (10 tests), the engine wired into the
  Phase 0 evaluation runner, the first honest engine baseline,
  `scripts/check_phase1.ps1`, and refreshed documentation including the
  threat-model enforcement status.
- Verification: `scripts/check_phase1.ps1 -SkipSync` exited 0 — 266 tests passed
  in 8.59 s, Ruff clean, strict MyPy clean on 74 source files, dataset 6/40/24
  valid, both tracked baselines unchanged. Baseline generation and `--check` both
  exited 0.
- Gate evidence: all eight `CLAUDE.md` Section 20 Phase 1 items are proven by
  named tests, including identical evidence from the application service, REST,
  and CLI for the same snapshot.
- Baseline honesty: 5 of 5 supported cases resolved; 35 of 40 cases abstain by
  design; `targets_met` is `false` and correctly so. `valid_evidence_rate` 0.8000
  reflects one gold-range granularity disagreement (`q009`), not invalid
  evidence: no emitted evidence fell outside real file bounds and no gold case
  was edited.
- Limitations: one intent; no relations, languages, change analysis, UI, or
  provider; synchronous full-rebuild indexing; UNC rejected; a Git subdirectory
  yields no Git state; the `q009` granularity decision is deferred.
- Next: the user approves the Phase 1 gate or requests changes.

### 2026-07-25T19:51:52Z — P1-09 completed; P1-10 started

- Agent: Claude Code `claude-opus-5`
- Transition: P1-09 `in_progress -> complete`; P1-10 `pending -> in_progress`.
- Outcome: Typer CLI implemented test-first with `--json` and human output and
  documented exit codes; CLI and REST proven to return identical evidence.
- Verification: 11 task tests passed after failing first; full suite 251 passed
  in 8.28 s; Ruff clean; strict MyPy clean on 70 source files; manual
  console-script run succeeded end to end. All exit code 0 except the deliberate
  abstention exit 4.
- Defect found by manual verification and fixed: UTF-8 files with a byte-order
  mark failed to parse, so anything written by common Windows tooling produced a
  parse error and no symbols. The parser now strips the BOM and offsets spans by
  its length; excerpts decode with `utf-8-sig`. Regression test added.
- Limitation: `index` blocks with no progress output or cancellation.
- Next: P1-10 test-first.

### 2026-07-25T19:47:23Z — P1-08 completed; P1-09 started

- Agent: Claude Code `claude-opus-5`
- Transition: P1-08 `in_progress -> complete`; P1-09 `pending -> in_progress`.
- Outcome: `/v1` REST adapter implemented test-first over the existing services.
- Verification: 19 task tests passed after failing first; full suite 239 passed
  in 7.52 s; Ruff clean; strict MyPy clean on 67 source files. All exit code 0.
- Security: loopback bind and absent CORS asserted by test; error bodies carry no
  trace, path, or exception message; validation errors do not echo the payload.
- Deviation: one reused WAL connection closed by a lifespan handler, instead of
  the planned per-request connection — single-user, single-writer profile.
- Limitation: `POST /index` is synchronous and blocks for the run.
- Next: P1-09 test-first.

### 2026-07-25T19:43:07Z — P1-07 completed; P1-08 started

- Agent: Claude Code `claude-opus-5`
- Transition: P1-07 `in_progress -> complete`; P1-08 `pending -> in_progress`.
- Outcome: `application/lookup.py` and `application/status.py` implemented
  test-first; the container now exposes registration, indexing, lookup, status.
- Verification: 25 task tests passed after failing first; full suite 220 passed
  in 10.23 s; Ruff clean; strict MyPy clean on 60 source files. All exit code 0.
- Trust behavior proven: distinct derivation for evidence and claims, abstention
  without invention, stale-content detection by hash with evidence withheld,
  unreadable-file handling, and full contract round-trip.
- Storage note: `index_jobs.diagnostics` now stores a JSON object rather than an
  array. Same column type, so no migration.
- Limitations: only the `exact_symbol` intent; excerpts bounded to 200 lines and
  8000 characters; `status` does not re-verify file drift, `lookup` does.
- Next: P1-08 test-first.

### 2026-07-25T19:39:05Z — P1-06 completed; P1-07 started

- Agent: Claude Code `claude-opus-5`
- Transition: P1-06 `in_progress -> complete`; P1-07 `pending -> in_progress`.
- Outcome: `application/registration.py`, `application/indexing.py`, and
  `application/container.py` implemented test-first. Register → scan → Git →
  parse → stage → validate → activate now works end to end.
- Verification: 17 task tests passed after failing first; full suite 195 passed
  in 7.06 s; Ruff clean; strict MyPy clean on 56 source files. All exit code 0.
- Invariants proven: idempotent re-index, supersede on change, previous active
  snapshot preserved on validation failure, non-Git directory still activates,
  malformed Python counted not fatal, no repository code executed.
- Correction: replaced a bare `assert` on the post-activation read with an
  explicit `SnapshotValidationError`, since asserts vanish under `-O`.
- Limitations: synchronous in-process indexing, no cancellation, full rebuild on
  any change (incremental reuse is Phase 2).
- Next: P1-07 test-first.

### 2026-07-25T19:35:07Z — P1-05 completed; P1-06 started

- Agent: Claude Code `claude-opus-5`
- Transition: P1-05 `in_progress -> complete`; P1-06 `pending -> in_progress`.
- Outcome: `parsing/registry.py` and `parsing/python_parser.py` implemented
  test-first. `ast` is authoritative for structure and lines; Tree-sitter
  supplies byte spans and recovers symbols from files `ast` rejects.
- Verification: 24 task tests passed after failing first; full suite 178 passed
  in 5.29 s; Ruff clean; strict MyPy clean on 52 source files. All exit code 0.
- Identity behavior proven by test: repeated parses are byte-identical in
  `symbol_id` and `symbol_version_id`; a body edit moves the version ID only.
- Security proven by test: no execution of module-level code or import side
  effects, no execution primitives in the module, oversized and undecodable
  content rejected with diagnostics, malformed and deeply nested input handled.
- Limitations: no relations (Phase 3), docstrings unstored, Python only.
- Next: P1-06 test-first.

### 2026-07-25T19:30:39Z — P1-04 completed; P1-05 started

- Agent: Claude Code `claude-opus-5`
- Transition: P1-04 `in_progress -> complete`; P1-05 `pending -> in_progress`.
- Outcome: snapshot/symbol domain types, SQLite connection with ADR-0002
  pragmas, the numbered migration runner, migration 0001, and the five stores.
- Migration: `SCHEMA_VERSION = 1`, forward-only, rollback is deleting the file.
- Verification: 25 task tests passed after failing first; full suite 154 passed
  in 4.39 s; Ruff clean; strict MyPy clean on 48 source files. All exit code 0.
- Design decision: migrations execute statement by statement inside an explicit
  `BEGIN IMMEDIATE` because `executescript` implicitly commits, which would leave
  a failed migration half applied. Boundaries come from
  `sqlite3.complete_statement`.
- Invariants moved into the schema and covered by tests: one active snapshot per
  repository (partial unique index), unique canonical root, cascading deletes,
  and symbols that cannot outlive their file within a snapshot.
- Next: P1-05 test-first.

### 2026-07-25T19:25:56Z — P1-03 completed; P1-04 started

- Agent: Claude Code `claude-opus-5`
- Transition: P1-03 `in_progress -> complete`; P1-04 `pending -> in_progress`.
- Outcome: `repositories/git_state.py` implemented test-first, with the real
  `git_repo` fixture added to `tests/conftest.py`.
- Verification: 11 task tests passed after failing first; full suite 129 passed
  in 4.30 s; Ruff clean; strict MyPy clean on 41 source files. All exit code 0.
- Defect found and fixed: a directory nested inside another Git repository
  inherited that repository's HEAD, branch, and dirty state. The adapter now
  requires `rev-parse --show-toplevel` to equal the approved root and otherwise
  returns `GIT_ROOT_MISMATCH` with no Git facts.
- Product consequence to carry forward: registering a subdirectory of a Git
  repository indexes normally but records no Git state. Changing that requires
  an explicit product decision.
- Security: no `shell=True` or `os.system` in the module (asserted by test);
  roots named like Git options degrade rather than inject.
- Next: P1-04 test-first.

### 2026-07-25T19:22:17Z — P1-02 completed; P1-03 started

- Agent: Claude Code `claude-opus-5`
- Transition: P1-02 `in_progress -> complete`; P1-03 `pending -> in_progress`.
- Outcome: `ignore_rules.py`, `classification.py`, and `scanner.py` implemented
  test-first.
- Verification: 43 task tests passed after failing first; full suite 118 passed
  in 1.42 s; Ruff clean; strict MyPy clean on 39 source files. All exit code 0.
- Defects fixed: directory-only ignore patterns now exclude descendants when
  queried directly; the scanner no longer derives relative paths through
  `realpath`, so a junction escape is reported as `OUTSIDE_ROOT` with a
  `SECURITY_LINK_ESCAPE` warning under its own name.
- Limitation: `**`, `?`, and character-class ignore patterns are unsupported and
  reported rather than approximated.
- Next: P1-03 test-first.

### 2026-07-25T19:04:58Z — P1-01 completed; P1-02 started

- Agent: Claude Code `claude-opus-5`
- Transition: P1-01 `in_progress -> complete`; P1-02 `pending -> in_progress`.
- Outcome: `domain/errors.py`, `domain/ids.py`, `domain/paths.py`, and
  `domain/repository.py` implemented test-first. Path validity delegates to the
  contract's `RepositoryRelativePath` rule; no second validator was introduced.
- Verification: tests observed failing first; then 25 passed for the task, 75
  passed for the full suite, Ruff clean, strict MyPy clean on 33 source files.
  All exit code 0.
- Security: traversal, absolute, backslash, blank, root-itself, reserved device
  name, UNC, and a real Windows junction escape are rejected under test.
- Limitation: UNC roots are rejected rather than supported behind an opt-in.
- Next: P1-02 test-first.

### 2026-07-25T18:59:40Z — Phase 1 approved; P1-SETUP completed; P1-01 started

- Agent: Claude Code `claude-opus-5`
- Transition: Phase 1 `ready -> in_progress`; P1-SETUP `ready -> complete`;
  P1-01 `pending -> in_progress`.
- Outcome: Dependencies locked (`tree-sitter==0.26.0`,
  `tree-sitter-python==0.25.0`, `fastapi==0.140.0`, `uvicorn==0.51.0`,
  `typer==0.27.0`, dev `httpx==0.28.1`), Tree-sitter Python bundle verified,
  tooling extended, package skeleton created, ADR-0002 accepted.
- Verification: `uv run pytest -q` — 50 passed; Ruff clean; strict MyPy clean on
  26 source files; `scripts/check_phase0.ps1 -SkipSync` completed with the
  tracked null baseline unchanged. All exit code 0.
- Deviation: used `str(node)` instead of the deprecated `Node.sexp()` in the
  parser smoke check.
- Limitation: the `codeatlas` console script points at a module that lands in
  P1-09.
- Next: P1-01 test-first.

### 2026-07-25T18:37:04Z — Phase 1 plan created; awaiting user approval

- Agent: Claude Code `claude-opus-5`
- Transition: Phase 1 `pending -> ready`; P1-SETUP created with status `ready`.
- Outcome: Wrote this shared execution plan from the actual tree, the Phase 0
  artifacts, `CLAUDE.md` Sections 20 and 26, and blueprint Sections 4.3, 4.4,
  4.7, and 9. No implementation, dependency, or configuration change was made.
- Files: `docs/plans/phases/phase-01-repository-truth-vertical-slice.md` (new)
  and `docs/plans/PLAN.md` (phase index, active work, plan rules, handoff).
- Contracts/migrations: None. Contract `1.0` is reused unchanged; the SQLite
  schema is specified here but not yet created.
- Verification: Documentation-only change; no executable tests were run. The
  current release-gate evidence remains the Phase 0 entry of
  2026-07-25T16:16:02Z.
- Git state: repository initialized on branch `main`, no commits yet, all files
  untracked, so no commit SHA accompanies this entry.
- Limitations: Dependency versions in the plan are the latest published on
  2026-07-25 and must be re-resolved and locked by P1-SETUP.
- Next: User approves or amends this plan. On approval, an agent moves P1-SETUP
  from `ready` to `in_progress` and starts with its Step 1.

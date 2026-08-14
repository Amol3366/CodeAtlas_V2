# Gate Exit Codes and Test Isolation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make two pytest runs safe to run at the same time, and make every release gate state its verdict in its exit code rather than implying it.

**Architecture:** Two independent fixes plus one records correction. The first removes the cause of four void gate runs — `--basetemp=.test-tmp` is a *shared* directory that pytest wipes wholesale, so a second run destroys a first run's live files. The root stays repository-local; only the leaf becomes per-session. The second appends an explicit `exit 0` to all eight gate scripts, which matters for callers that read `$LASTEXITCODE`. The third corrects two Deferred Register rows whose stated diagnoses this plan disproved.

**Tech Stack:** Python 3.12, pytest 9.1.1, PowerShell (Windows PowerShell 5.1). **No new dependency.**

**Spec:** The Deferred Register in `docs/plans/PLAN.md` (rows "`check_phase7.ps1` can exit non-zero while reporting success" and "`.test-tmp` residue and concurrency void gate runs"), and the "Two fixes worth doing before Task 3" section of `docs/superpowers/plans/2026-08-14-post-closeout-program.md`. **Both register rows state a mechanism that measurement contradicts — see Findings below. Where this plan and the register disagree about the mechanism, this plan is the newer measurement; the register rows are corrected by Task 3.**

## Global Constraints

- `AGENTS.md` is the release-blocking contract. `docs/plans/PLAN.md` is live status; append handoffs, never rewrite them.
- **Test-first.** No production code without a test observed failing first, and mutation-check every fix.
- **Revert a mutation from a file copy, never `git checkout --`.** It has twice reverted the fix along with the mutation (ADR-0022, ADR-0042).
- **Do not edit the tree you are measuring.**
- No change to `PARSER_BUNDLE_VERSION`, `RESOLVER_VERSION`, `CHUNKER_VERSION`, `SCHEMA_VERSION` (14), or `contract_version` (1.1). Nothing here touches the engine, so no snapshot goes stale.
- `tests/conftest.py` is deliberately **the only** conftest module in the suite. Its own comment records why: "a second conftest module collides with this one under mypy." **Do not add a second one.**
- Gates before any completion claim, run one at a time until Task 1 lands: `uv run pytest -q`, `ruff check src tests scripts apps`, `mypy --no-incremental src tests scripts apps`, `check_phase4.ps1 -SkipSync`, `check_phase7.ps1 -SkipSync`. Record exact commands and exit codes read from the process.

---

## Findings that change this plan

Measured 2026-08-14, before writing it. Both register rows were written from inference rather than reproduction, and this is the **seventh** time in this project that an investigation has found the instrument rather than the engine at fault (ADR-0017, 0018, 0024, 0027, 0038, the 2026-08-13 document-section report, and now this).

**Finding 1 — the `.test-tmp` mechanism is worse than "residue", and a lockfile is the wrong fix.**

`pyproject.toml` pins `addopts = "... --basetemp=.test-tmp"`. Measured behaviour of pytest 9.1.1: when given an explicit `--basetemp`, pytest **deletes that entire directory** at the moment the first `tmp_path` is requested, then creates per-test directories directly inside it. There is no per-session numbered subdirectory, and none of pytest's usual retention applies.

Proof — a marker planted in `.test-tmp` before a run that uses `tmp_path`:

```
marker survived? -> NO - WIPED
contents: test_uses_tmp_path0
```

So a second run does not merely collide on creation; it **destroys a running session's live temporary files underneath it**. That explains `FileExistsError`, the "residue fails the next gate" reports, and plausibly the long-standing `sqlite3.OperationalError: disk I/O error` flake in `test_a_genuinely_killed_process_is_recovered_and_can_reindex`.

A lockfile would serialize runs and leave the shared-directory design in place, and would need stale-lock detection — the pid-ownership problem ADR-0037 had to solve. Per-session directories remove the collision instead of scheduling around it. **Decision taken by the project owner 2026-08-14: per-session basetemp.**

**Finding 2 — the gate scripts are *not* broken in the way the register claims.**

The register says `check_phase7.ps1` "exits with whatever the last native command left". Measured, with three one-line PowerShell scripts:

| Script | Invocation | Exit |
| --- | --- | --- |
| trailing `cmd /c "exit 3"`, no `exit 0` | `powershell -File` | **0** |
| trailing `cmd /c "exit 3"`, no `exit 0` | `powershell -Command "& ./s.ps1"` | **0** |
| trailing `cmd /c "exit 3"`, no `exit 0` | called from a wrapper `.ps1` that does `exit $LASTEXITCODE` | **3** |
| trailing `cmd /c "exit 3"`, **with** `exit 0` | same wrapper | **0** |
| `throw "step failed"`, with `exit 0` below it | `powershell -File` | **1** |

So: **on the documented invocation form the success path already exits 0**, and the failure path already exits non-zero because `$ErrorActionPreference = "Stop"` plus `Invoke-Checked`'s `throw` terminates before reaching the bottom of the script. The last row is the one that matters for safety — adding `exit 0` **cannot mask a failing step**, because a throw never reaches it.

The real exposure is the third row: **any caller that reads `$LASTEXITCODE` after invoking a gate** — a wrapper script, a CI step, another `.ps1` — sees the stale code of the gate's last native command. That is a narrower defect than recorded, and it is still worth fixing, because a release gate should state its verdict rather than leave it to the caller's invocation form.

**Consequence for expectations:** do not expect this task to explain the unattributed intermittent (a `check_phase7` run that exited 1 while printing every step as passing). Exit 1 is the *uncaught-throw* signature, so something threw. `exit 0` will not change that, and the intermittent stays open.

---

## File Structure

| File | Responsibility | Task |
| --- | --- | --- |
| `pyproject.toml` | Stops pinning a shared `--basetemp` | 1 |
| `tests/conftest.py` | Gains the per-session basetemp hook and the pruner | 1 |
| `tests/unit/test_temporary_directories.py` | **New.** Pins per-session isolation and pruning | 1 |
| `scripts/check_phase0..7.ps1` | Each gains a trailing `exit 0` | 2 |
| `tests/unit/test_gate_exit_codes.py` | **New.** Pins the exit-code contract, statically and dynamically | 2 |
| `docs/plans/PLAN.md` | Register rows corrected; handoff appended | 3 |
| `documentation/memory.md` | Session log | 3 |

Two new test modules rather than additions to existing ones: `tests/unit/test_gate_script_invocations.py` and `tests/unit/test_gate_flag_combinations.py` each pin one gate-script property and are named for it, so a third property gets a third file. That is the established pattern here.

---

### Task 1: Per-session temporary directories

**Files:**
- Modify: `pyproject.toml:62`
- Modify: `tests/conftest.py` (add imports and the hook; do not disturb `collect_ignore_glob`)
- Test: `tests/unit/test_temporary_directories.py` (create)

**Interfaces:**
- Produces: `TEST_TMP_ROOT: Path` (value `Path(".test-tmp")`), `_prune_old_sessions(root: Path) -> None`, and a `pytest_configure(config: pytest.Config) -> None` hookimpl marked `tryfirst=True`. Task 2 consumes none of these.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_temporary_directories.py`:

```python
"""Each pytest session owns its own temporary directory.

`--basetemp` used to be pinned to the shared `.test-tmp`, and pytest *deletes
the directory it is given* when the first `tmp_path` is requested -- not a
numbered subdirectory of it, the directory itself. Two runs therefore destroyed
each other's live files, which is why four gate runs in two days were void and
why the post-closeout program carries a rule saying never to run two at once.

These tests pin the replacement: a repository-local root, a per-session leaf,
and a pruner that cannot delete a directory another run is still using.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.conftest import (
    TEST_TMP_ROOT,
    _prune_old_sessions,
    pytest_configure,
)


def _config(basetemp: str | None = None) -> SimpleNamespace:
    """The two attributes the hook reads. A real Config needs a full session."""
    return SimpleNamespace(option=SimpleNamespace(basetemp=basetemp))


def test_the_session_basetemp_is_inside_the_repository_local_root(
    tmp_path: Path,
) -> None:
    """The root stays in the repository on purpose.

    `docs/operations/development-windows.md` records that a locked-down Windows
    account may be unable to write the system temp directory, which is why this
    is not simply pytest's default.
    """
    assert TEST_TMP_ROOT.name == ".test-tmp"
    resolved = tmp_path.resolve()
    assert TEST_TMP_ROOT.resolve() in resolved.parents


def test_two_sessions_are_given_different_directories() -> None:
    """The whole fix in one assertion."""
    first, second = _config(), _config()

    pytest_configure(first)  # type: ignore[arg-type]
    pytest_configure(second)  # type: ignore[arg-type]

    assert first.option.basetemp != second.option.basetemp


def test_an_explicit_basetemp_is_left_alone() -> None:
    """`pytest --basetemp=X` must still mean X, or debugging loses a tool."""
    config = _config(basetemp="/somewhere/chosen")

    pytest_configure(config)  # type: ignore[arg-type]

    assert config.option.basetemp == "/somewhere/chosen"


def test_a_stale_session_directory_is_pruned(tmp_path: Path) -> None:
    stale = tmp_path / "s-1234-abcdef12"
    stale.mkdir()
    (stale / "leftover.txt").write_text("old", encoding="utf-8")
    old = (datetime.now(UTC) - timedelta(hours=48)).timestamp()
    os.utime(stale, (old, old))

    _prune_old_sessions(tmp_path)

    assert not stale.exists()


def test_a_fresh_session_directory_is_kept(tmp_path: Path) -> None:
    """A live run's directory must survive another run's startup.

    This is the property the old design broke. Age is the test rather than
    ownership because a pid is a slot the OS reassigns (ADR-0037), so asking
    "does another pytest still own this?" has no reliable answer.
    """
    live = tmp_path / "s-5678-12345678"
    live.mkdir()
    (live / "in-use.txt").write_text("a run is using this", encoding="utf-8")

    _prune_old_sessions(tmp_path)

    assert (live / "in-use.txt").read_text(encoding="utf-8") == (
        "a run is using this"
    )


def test_pruning_ignores_anything_that_is_not_a_session_directory(
    tmp_path: Path,
) -> None:
    """Only `s-*` directories are ours. Nothing else is touched at any age."""
    stranger = tmp_path / "not-a-session"
    stranger.mkdir()
    old = (datetime.now(UTC) - timedelta(days=30)).timestamp()
    os.utime(stranger, (old, old))

    _prune_old_sessions(tmp_path)

    assert stranger.exists()


def test_the_shared_basetemp_is_no_longer_pinned() -> None:
    """The regression guard for the whole task.

    Restoring `--basetemp=.test-tmp` to `addopts` silently reinstates the
    shared directory and every test above keeps passing, because the hook would
    then see a basetemp already set and decline to override it.
    """
    addopts = Path("pyproject.toml").read_text(encoding="utf-8")

    assert "--basetemp" not in addopts
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `uv run pytest tests/unit/test_temporary_directories.py -q`
Expected: collection error — `ImportError: cannot import name 'TEST_TMP_ROOT' from 'tests.conftest'`. That is the correct first failure; nothing is implemented yet.

- [ ] **Step 3: Remove the shared basetemp from `pyproject.toml`**

Change line 62 from:

```toml
addopts = "-ra -p no:cacheprovider --basetemp=.test-tmp"
```

to:

```toml
addopts = "-ra -p no:cacheprovider"
```

- [ ] **Step 4: Add the hook to `tests/conftest.py`**

Extend the existing import block — `json`, `shutil`, `subprocess`, `Path` and `pytest` are already imported; add `os`, `uuid4`, and the `datetime` names:

```python
import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4
```

Then add this immediately after the `collect_ignore_glob` block, before the first fixture:

```python
# --- Per-session temporary directories ---------------------------------------
#
# `--basetemp` was pinned to `.test-tmp` in `pyproject.toml`, and pytest deletes
# the directory it is given the moment the first `tmp_path` is requested -- the
# directory itself, not a numbered subdirectory of it. Two runs therefore wiped
# each other's live files, which is why "never run two gates at once" had to be
# a written rule and why four runs in two days were void rather than red.
#
# The root stays repository-local deliberately: `development-windows.md` records
# that a locked-down Windows account may be unable to write the system temp
# directory. Only the leaf is per-session.
TEST_TMP_ROOT = Path(".test-tmp")
_SESSION_RETENTION = timedelta(hours=24)


def _prune_old_sessions(root: Path) -> None:
    """Delete session directories left behind by earlier runs.

    Age-based, not count-based, and never ownership-based: a live session's
    directory must never be removed, and a pid is a slot the OS reassigns
    (ADR-0037), so "is another pytest still using this?" has no reliable answer.
    A generous retention buys that safety cheaply -- these are temporary files
    on a developer's disk, not a resource under pressure.

    Every failure is ignored. A directory another process holds open is not a
    reason to fail the run that was only tidying up; that would trade the defect
    being fixed for a new one of the same shape.
    """
    cutoff = (datetime.now(UTC) - _SESSION_RETENTION).timestamp()
    for candidate in root.glob("s-*"):
        try:
            if candidate.is_dir() and candidate.stat().st_mtime < cutoff:
                shutil.rmtree(candidate, ignore_errors=True)
        except OSError:
            continue


@pytest.hookimpl(tryfirst=True)
def pytest_configure(config: pytest.Config) -> None:
    """Give this session its own basetemp under the shared root.

    `tryfirst` is load-bearing: pytest's own `tmpdir` plugin reads `basetemp` in
    its `pytest_configure`, so this has to win the race to set it.

    An explicit `--basetemp` is honoured untouched -- passing one is how you ask
    to inspect a specific run's files, and overriding that would take away a
    debugging tool to fix a concurrency bug.

    The suffix is a uuid rather than a timestamp because Windows clock
    granularity is coarse enough that four processes launched together observed
    the *same* `time.time_ns()`; only the pid differed, and pids are reused.
    """
    if config.option.basetemp is not None:
        return
    TEST_TMP_ROOT.mkdir(parents=True, exist_ok=True)
    _prune_old_sessions(TEST_TMP_ROOT)
    config.option.basetemp = str(
        TEST_TMP_ROOT / f"s-{os.getpid()}-{uuid4().hex[:8]}"
    )
```

- [ ] **Step 5: Run the tests and watch them pass**

Run: `uv run pytest tests/unit/test_temporary_directories.py -q`
Expected: `7 passed`.

- [ ] **Step 6: Prove the fix on the real defect, which no unit test covers**

The unit tests pin the hook; they do not prove two *processes* stop colliding. Run the thing the program plan currently forbids:

```bash
rm -rf .test-tmp
uv run pytest tests/integration -q > /tmp/run-a.log 2>&1 &
uv run pytest tests/unit -q > /tmp/run-b.log 2>&1 &
wait
tail -1 /tmp/run-a.log; tail -1 /tmp/run-b.log
ls .test-tmp
```

Expected: both runs pass, and `.test-tmp` holds two distinct `s-<pid>-<uuid>` directories. Record both tail lines in the handoff — this is the evidence the rule can be retired.

- [ ] **Step 7: Mutation-check the regression guard**

Every test above passes on first run once implemented, which proves nothing on its own. Restore the shared basetemp and confirm the guard fires:

```bash
cp pyproject.toml /tmp/pyproject.toml.orig
sed -i 's|addopts = "-ra -p no:cacheprovider"|addopts = "-ra -p no:cacheprovider --basetemp=.test-tmp"|' pyproject.toml
uv run pytest tests/unit/test_temporary_directories.py -q
```

Expected: `test_the_shared_basetemp_is_no_longer_pinned` **fails**, and
`test_the_session_basetemp_is_inside_the_repository_local_root` also fails
because `tmp_path` is then directly under `.test-tmp` with no `s-` leaf.

Restore **from the copy, never `git checkout --`**:

```bash
cp /tmp/pyproject.toml.orig pyproject.toml
uv run pytest tests/unit/test_temporary_directories.py -q   # 7 passed again
```

- [ ] **Step 8: Run the full suite**

Run: `uv run pytest -q`
Expected: `2212 passed, 3 skipped` — the same counts as commit `f4fdae4`, plus the 7 new tests, so **2219 passed, 3 skipped**. Any other number means this task changed behaviour it had no business changing; stop and investigate before continuing.

- [ ] **Step 9: Lint and types**

```bash
uv run ruff check src tests scripts apps
uv run mypy --no-incremental src tests scripts apps
```
Expected: clean, and mypy reports 351 source files (350 plus the new test module).

- [ ] **Step 10: Commit**

```bash
git add pyproject.toml tests/conftest.py tests/unit/test_temporary_directories.py
git commit -m "fix(tests): give each pytest session its own temporary directory"
```

---

### Task 2: A gate script states its verdict

**Files:**
- Modify: `scripts/check_phase0.ps1`, `check_phase1.ps1`, `check_phase2.ps1`, `check_phase3.ps1`, `check_phase4.ps1`, `check_phase5.ps1`, `check_phase6.ps1`, `check_phase7.ps1` (append one line to each)
- Test: `tests/unit/test_gate_exit_codes.py` (create)

**Interfaces:**
- Consumes: nothing from Task 1.
- Produces: nothing consumed by Task 3.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_gate_exit_codes.py`:

```python
"""A gate script states its verdict in its exit code.

Measured before this was written, because the Deferred Register's stated
mechanism turned out to be wrong. With `powershell -File`, a trailing native
command's non-zero `$LASTEXITCODE` does *not* become the process exit code --
the success path already exited 0. The real exposure is narrower: a caller that
reads `$LASTEXITCODE` after invoking the gate (a wrapper script, a CI step,
another .ps1) sees the stale code of whatever the gate ran last.

The safety property is the one worth pinning hardest: because
`$ErrorActionPreference = "Stop"` and `Invoke-Checked` throws, a failing step
terminates the script before it can reach the trailing `exit 0`. The line
cannot convert a red gate into a green one, and
`test_a_failing_step_still_exits_non_zero_despite_the_trailing_exit` is what
keeps that true.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

SCRIPTS = Path("scripts")

_WINDOWS_ONLY = pytest.mark.skipif(
    os.name != "nt",
    reason="PowerShell exit-code semantics are the Windows behaviour under test",
)


def _gate_scripts() -> list[Path]:
    found = sorted(SCRIPTS.glob("check_phase*.ps1"))
    assert found, "no gate scripts found; the guard would pass vacuously"
    return found


def _last_statement(script: Path) -> str:
    lines = [
        stripped
        for line in script.read_text(encoding="utf-8").splitlines()
        if (stripped := line.strip()) and not stripped.startswith("#")
    ]
    return lines[-1]


@pytest.mark.parametrize("script", _gate_scripts(), ids=lambda p: p.name)
def test_every_gate_script_ends_by_exiting_zero(script: Path) -> None:
    """All eight, not just the one the register named.

    A guard carrying an exemption list is weaker than the rule it encodes, and
    invites the next script to be added broken.
    """
    assert _last_statement(script) == "exit 0", (
        f"{script.name} does not end with an explicit `exit 0`, so a caller "
        "reading $LASTEXITCODE gets whatever its last native command left."
    )


def _run_script(script: Path) -> int:
    completed = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script),
        ],
        capture_output=True,
        text=True,
        cwd=script.parent,
    )
    return completed.returncode


_TRAILING_FAILURE = (
    '$ErrorActionPreference = "Stop"\n'
    'cmd /c "exit 3"\n'
    'Write-Output "verification completed."\n'
)


@_WINDOWS_ONLY
def test_a_caller_reading_lastexitcode_sees_a_stale_code_without_the_line(
    tmp_path: Path,
) -> None:
    """Why the line is worth adding at all.

    The wrapper is the shape that exposes it: `-File` on its own returns 0 here,
    which is exactly why this went unnoticed.
    """
    (tmp_path / "gate.ps1").write_text(_TRAILING_FAILURE, encoding="utf-8")
    wrapper = tmp_path / "wrapper.ps1"
    wrapper.write_text(
        '$ErrorActionPreference = "Stop"\n'
        '& "./gate.ps1"\n'
        "exit $LASTEXITCODE\n",
        encoding="utf-8",
    )

    assert _run_script(wrapper) == 3


@_WINDOWS_ONLY
def test_the_trailing_exit_zero_stops_the_stale_code_reaching_the_caller(
    tmp_path: Path,
) -> None:
    (tmp_path / "gate.ps1").write_text(
        _TRAILING_FAILURE + "exit 0\n", encoding="utf-8"
    )
    wrapper = tmp_path / "wrapper.ps1"
    wrapper.write_text(
        '$ErrorActionPreference = "Stop"\n'
        '& "./gate.ps1"\n'
        "exit $LASTEXITCODE\n",
        encoding="utf-8",
    )

    assert _run_script(wrapper) == 0


@_WINDOWS_ONLY
def test_a_failing_step_still_exits_non_zero_despite_the_trailing_exit(
    tmp_path: Path,
) -> None:
    """The safety property. Without this, the fix could hide a red gate.

    `Invoke-Checked` throws on a non-zero step and `$ErrorActionPreference` is
    `Stop`, so the script terminates above the trailing line and never runs it.
    """
    gate = tmp_path / "gate.ps1"
    gate.write_text(
        '$ErrorActionPreference = "Stop"\n'
        'throw "step failed"\n'
        'Write-Output "verification completed."\n'
        "exit 0\n",
        encoding="utf-8",
    )

    assert _run_script(gate) == 1
```

- [ ] **Step 2: Run the tests and watch the right one fail**

Run: `uv run pytest tests/unit/test_gate_exit_codes.py -q`
Expected: the three dynamic tests **pass** (they test PowerShell, not our scripts), and
`test_every_gate_script_ends_by_exiting_zero` **fails for all eight** parametrized cases with "does not end with an explicit `exit 0`". Eight failures is the correct starting state.

- [ ] **Step 3: Append `exit 0` to all eight gate scripts**

One line at the end of each of `scripts/check_phase0.ps1` through `check_phase7.ps1`. For `check_phase0`–`check_phase5`, whose last statement is a single `Write-Output`, the file ends:

```powershell
Write-Output "Phase 4 verification completed."

# The verdict belongs in the exit code, not only in the line above it. Without
# this, a caller that reads $LASTEXITCODE after invoking the gate gets whatever
# the last native command left -- measured at 3 for a wrapper script. A failing
# step never reaches here: Invoke-Checked throws and $ErrorActionPreference is
# Stop, which tests/unit/test_gate_exit_codes.py pins.
exit 0
```

For `check_phase6.ps1` and `check_phase7.ps1`, whose last statement is the closing `}` of an if/else over the end-to-end message, the `exit 0` goes **after** the closing brace so both branches reach it:

```powershell
if ($SkipE2E) {
    Write-Output "Phase 7 verification completed (end-to-end skipped)."
} else {
    Write-Output "Phase 7 verification completed."
}

# See the comment pattern above; both branches fall through to here.
exit 0
```

- [ ] **Step 4: Run the tests and watch them pass**

Run: `uv run pytest tests/unit/test_gate_exit_codes.py -q`
Expected: `11 passed` (8 parametrized + 3 dynamic).

- [ ] **Step 5: Mutation-check the guard**

```bash
cp scripts/check_phase4.ps1 /tmp/check_phase4.ps1.orig
python -c "
from pathlib import Path
p = Path('scripts/check_phase4.ps1')
p.write_text(p.read_text(encoding='utf-8').replace('\nexit 0\n', '\n'), encoding='utf-8')
"
uv run pytest tests/unit/test_gate_exit_codes.py -q
```

Expected: `test_every_gate_script_ends_by_exiting_zero[check_phase4.ps1]` fails and the other seven pass. Restore **from the copy**:

```bash
cp /tmp/check_phase4.ps1.orig scripts/check_phase4.ps1
uv run pytest tests/unit/test_gate_exit_codes.py -q   # 11 passed
```

- [ ] **Step 6: Prove the real gates still behave, both ways**

A gate that now exits 0 must still exit non-zero when a step genuinely fails. Run one gate green, then one deliberately broken:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/check_phase4.ps1 -SkipSync
"exit=$LASTEXITCODE"
```
Expected: `exit=0`.

Then temporarily point the Phase 4 gate's dataset at a path that does not exist (edit the `--dataset` argument of the "Dataset validation" step to `tests/evaluation/does-not-exist`), re-run, and expect a **non-zero** exit with the failure named in the log. Restore the script from a copy afterwards. **Do not skip this step** — it is the only direct evidence that `exit 0` did not turn the gate into a rubber stamp.

- [ ] **Step 7: Commit**

```bash
git add scripts/check_phase*.ps1 tests/unit/test_gate_exit_codes.py
git commit -m "fix(scripts): every gate script states its verdict in its exit code"
```

---

### Task 3: Correct the register and record the work

**Files:**
- Modify: `docs/plans/PLAN.md` (two Deferred Register rows; append one handoff entry)
- Modify: `documentation/memory.md` (append to Completed)
- Modify: `docs/superpowers/plans/2026-08-14-post-closeout-program.md` (retire the concurrency constraint)

- [ ] **Step 1: Replace the `.test-tmp` register row**

Its stated remedy ("A lockfile around `.test-tmp` plus clean-on-start") is now wrong, and the row must not be left implying a lockfile was the answer. Replace the whole row with:

```markdown
| ~~`.test-tmp` residue and concurrency void gate runs~~ | **CLOSED 2026-08-14.** The cause was not residue and the fix was not a lockfile. `--basetemp=.test-tmp` was a *shared* directory, and pytest **deletes the directory it is given** when the first `tmp_path` is requested — so a second run destroyed a running session's live files rather than merely colliding with it. Each session now gets `.test-tmp/s-<pid>-<uuid>`, pruned by age on start; the root stays repository-local because a locked-down Windows account may be unable to write system temp. A lockfile was rejected: it would serialize runs instead of making them safe, and would need stale-lock detection — the pid-ownership problem ADR-0037 had to solve. **The "never run two gates at once" rule is retired**, proven by two concurrent suites both passing | — |
```

- [ ] **Step 2: Replace the gate exit-code register row**

```markdown
| ~~`check_phase7.ps1` can exit non-zero while reporting success~~ | **CLOSED 2026-08-14, with the diagnosis corrected.** The recorded mechanism ("exits with whatever the last native command left") **does not reproduce**: under `powershell -File` a trailing `cmd /c "exit 3"` still exits **0**, and a failing step already exits non-zero because `Invoke-Checked` throws under `$ErrorActionPreference = "Stop"`. The real exposure is one form narrower — a **caller** that reads `$LASTEXITCODE` after invoking a gate sees the stale code, measured at 3 through a wrapper script. All **eight** gate scripts lacked the line, not just Phase 7. Each now ends `exit 0`, pinned statically and by three dynamic tests, one of which asserts a throwing step still exits non-zero so the line can never convert red to green. **The unattributed intermittent is not explained by this** — exit 1 is the uncaught-throw signature, so it stays open | — |
```

- [ ] **Step 3: Retire the concurrency constraint in the program plan**

In `docs/superpowers/plans/2026-08-14-post-closeout-program.md`, replace the Global Constraints bullet that begins "**Never run two gates, or a gate and a pytest, concurrently.**" with:

```markdown
- ~~Never run two gates, or a gate and a pytest, concurrently.~~ **Retired 2026-08-14.** They no longer share a temporary directory: each session gets `.test-tmp/s-<pid>-<uuid>`. The rule existed because pytest wipes the `--basetemp` it is given, so a second run destroyed the first run's live files.
```

Also strike the "Two fixes worth doing before Task 3" section's two bullets, marking each done and noting that the lockfile was rejected in favour of per-session directories.

- [ ] **Step 4: Append the handoff entry to `docs/plans/PLAN.md`**

Newest entries go at the **top** of the Handoff Log, immediately under the `## Handoff Log` heading. It must record: both corrected diagnoses; that this is the seventh instrument-not-engine finding; the two concurrent-run tail lines from Task 1 Step 6; the both-ways gate evidence from Task 2 Step 6; and exact commands with exit codes read from the process.

- [ ] **Step 5: Append to `documentation/memory.md`**

A `- [x]` entry under Completed. The transferable lessons, which are the point of that file:
  1. **A remedy written into the register is still a hypothesis.** Both rows named a mechanism that measurement contradicted.
  2. **pytest deletes the `--basetemp` you give it.** Sharing one across runs is the bug, not the residue in it.
  3. **`powershell -File` does not propagate a trailing native exit code**; a wrapper reading `$LASTEXITCODE` does.

- [ ] **Step 6: Run every gate one final time and commit**

```bash
uv run pytest -q
uv run ruff check src tests scripts apps
uv run mypy --no-incremental src tests scripts apps
powershell -ExecutionPolicy Bypass -File scripts/check_phase4.ps1 -SkipSync
powershell -ExecutionPolicy Bypass -File scripts/check_phase7.ps1 -SkipSync
git add docs/ documentation/
git commit -m "docs: close the gate exit-code and test-isolation rows, with corrected diagnoses"
```

Record each exit code from `$LASTEXITCODE`, not from the log line — which is, after Task 2, finally the same thing.

---

## Self-Review

**Spec coverage.** The register's two open rows both map to tasks: `.test-tmp` → Task 1, gate exit code → Task 2, and both rows are corrected and closed in Task 3. The program plan's "two fixes worth doing before Task 3" are the same two items and are struck in Task 3 Step 3. The owner's two decisions from 2026-08-14 are both honoured: per-session basetemp (Task 1) and all eight scripts (Task 2, asserted by a parametrized test with no exemption list).

**Placeholder scan.** No TBDs. Every code step carries the literal file content. The one step that cannot be given as fixed text — Task 2 Step 6's deliberate breakage — names the exact edit (the `--dataset` argument of the "Dataset validation" step) and the exact expectation.

**Type consistency.** `TEST_TMP_ROOT`, `_SESSION_RETENTION`, `_prune_old_sessions(root: Path) -> None` and `pytest_configure(config: pytest.Config) -> None` are defined in Task 1 Step 4 and imported under those exact names in Task 1 Step 1. The test module imports from `tests.conftest`, which resolves because `pythonpath = ["src", "."]` already includes the repository root. `_gate_scripts`, `_last_statement`, `_run_script` and `_TRAILING_FAILURE` are local to Task 2's module and used only there.

**Risks, stated rather than discovered.**

1. **`tryfirst` ordering is the one load-bearing assumption**, and it was verified by spike before this plan was written: `tmp_path` landed at `.test-tmp/s-17648-.../test_name0` and a sibling directory survived. If a future pytest changes when the `tmpdir` plugin reads `basetemp`, `test_the_session_basetemp_is_inside_the_repository_local_root` fails loudly rather than silently reverting to a shared directory.
2. **`exit 0` could in principle mask a failure.** It cannot here, and Task 2 Step 1's third dynamic test plus Step 6's deliberate breakage are both there to keep it that way. This is the highest-consequence risk in the plan and has two independent checks.
3. **Pruning could delete a live run's directory** if a session ran longer than 24 hours. It cannot in practice — the full suite is under 8 minutes — and the failure mode of a too-generous retention is only disk use.
4. **Task 1 changes test infrastructure used by all 2212 tests.** Step 8 pins the expected count exactly so an unrelated behaviour change cannot hide inside it.

**What this plan deliberately does not do.** It does not chase the unattributed `check_phase7` intermittent; exit 1 is the uncaught-throw signature and `exit 0` will not touch it, so it stays an open register row rather than being quietly folded in.

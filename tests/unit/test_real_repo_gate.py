"""The real-repository check is wired into a gate, and it never fetches there.

**This check has the best measured yield in the repository's history, and it
was not in any gate until 2026-09-04.** ADR-0041 to ADR-0045, ADR-0064 and
ADR-0069 were all found by running the product on real code. ADR-0069 alone
justifies the wiring: indexing a real repository failed outright -- `UNIQUE
constraint failed`, `INTERNAL_ERROR`, **no snapshot at all**, six of seven
languages -- and it had been latent **since Phase 1** while seven phases of
gates passed, because every evaluation fixture is a two-file toy. *A corpus
that cannot express a defect reads as coverage.*

Two properties are asserted here, and they pull against each other, which is
the whole design:

1. **The gate runs it.** Not behind an opt-in flag. This project has paid twice
   for opt-in legs -- `-Package` shipped an artifact to `main` that could not
   start, and `-Semantic` let two tracked baselines sit stale for two days.
   *The leg nobody runs is where the defect lives.*
2. **It cannot need a network.** A gate for a local-first product must be
   trustworthy offline, which is the objection that (rightly) kept this out of
   the gate until now. `--require-cached` reads pins already on disk and
   reports the rest as NOT CHECKED without failing.

Assert both or neither is safe: wiring it *without* `--require-cached` makes
the gate need the internet; adding `--require-cached` without the wiring checks
nothing.

**What this does NOT cover.** It is a static check on the scripts. It does not
run the repositories -- that needs a 16 MB cache and 75 seconds, which is the
gate's job, not a unit test's. It cannot detect a cache that is present but
stale at the wrong SHA; `cached_root` compares the SHA for that, and its own
behaviour is asserted below rather than assumed.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path("scripts/check_real_repos.py")
GATE = Path("scripts/check_phase7.ps1")

# The QUOTED form, because that is how the script appears in an `Invoke-Checked`
# argument array -- `"run", "python", "scripts/check_real_repos.py",`.
#
# Matching the bare name instead is wrong, and this guard proved it on its own
# first run: the gate's explanatory comment also names the script (`uv run
# python scripts/check_real_repos.py --workspace $ws`), so a bare search found
# the *comment* and asserted against the prose beneath it. **Defining or
# mentioning a path is not invoking it** -- the identical defect the packaging
# guard hit, where a test passed with the `--add-data` line deleted because a
# `Join-Path` assignment contained the same substring.
INVOCATION = '"scripts/check_real_repos.py"'


def test_a_gate_invokes_the_real_repository_check() -> None:
    """Some gate actually calls the script.

    Without this, the wiring is one careless edit from disappearing, and its
    absence looks exactly like its presence: a green gate either way. That is
    the failure mode that let the check sit ungated for two weeks after the
    defect it exists to catch was found.
    """
    assert SCRIPT.exists(), f"{SCRIPT} is missing; the gate step below invokes it"
    assert INVOCATION in GATE.read_text(encoding="utf-8"), (
        f"{GATE} no longer invokes {SCRIPT} as an argument-array step. The "
        "highest-yield check in this repository's history is only useful if "
        "something runs it -- see ADR-0069, which 2,400 passing tests could "
        "not see. A comment mentioning the script does not satisfy this."
    )


def test_the_gate_never_fetches() -> None:
    """The gate's invocation passes --require-cached.

    A gate that reaches the network is not trustworthy offline, and this
    product is local-first. This is the assertion that lets property 1 above
    exist at all: without it, wiring the check into the gate would be a
    regression rather than an improvement.
    """
    gate = GATE.read_text(encoding="utf-8")
    index = gate.find(INVOCATION)
    assert index != -1, "the gate no longer invokes the script; see the test above"

    # The rest of the argument array follows the script name, up to the `)`
    # that closes it. Bounded by the array rather than by a character count, so
    # a `--require-cached` belonging to some *later* step could not satisfy it.
    end = gate.find(")", index)
    assert end != -1, f"the {GATE} invocation's argument array is unterminated"

    assert "--require-cached" in gate[index:end], (
        "the gate invokes check_real_repos.py WITHOUT --require-cached, so a "
        "gate run would fetch from the network. A local-first product's gate "
        "must pass offline."
    )


def test_require_cached_is_refused_without_a_workspace() -> None:
    """`--require-cached` alone would pass having measured nothing.

    Without `--workspace` the clones go to a fresh temporary directory, which
    is empty by construction, so every target reports as not cached and the
    check exits 0 having done nothing. That is this project's most-recorded
    failure shape -- a green run that measured nothing -- so it is refused up
    front rather than tolerated.
    """
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--require-cached"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2, (
        "--require-cached without --workspace should be refused with exit 2, "
        f"got {result.returncode}: {result.stdout}{result.stderr}"
    )
    assert "--workspace" in result.stderr


def test_an_absent_cache_is_reported_and_does_not_fail(tmp_path: Path) -> None:
    """An empty workspace reports NOT CHECKED and still exits 0.

    This is the offline path, and it is the one that keeps the gate honest for
    someone with no cache. It must be **loud** -- the notice names every
    unchecked repository and the exact command that fixes it -- because a
    silent skip is how an opt-in leg goes unrun for two weeks.
    """
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--require-cached",
            "--workspace",
            str(tmp_path / "empty"),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, (
        "an absent cache must not fail the gate; a local-first gate has to "
        f"pass offline. Got {result.returncode}: {result.stderr}"
    )
    assert "NOT CHECKED" in result.stderr, (
        "an absent cache must be announced, not skipped silently: "
        f"{result.stdout}{result.stderr}"
    )
    assert "check_real_repos.py" in result.stderr, (
        "the notice must name the command that populates the cache"
    )


@pytest.mark.parametrize("state", ["missing", "not-a-checkout", "wrong-sha"])
def test_a_cache_hit_requires_the_pinned_sha(tmp_path: Path, state: str) -> None:
    """A cache hit is about the pin, not about the directory existing.

    A half-fetched directory, or one left at a previous pin, must not read as
    a hit -- it would index the wrong code and report success, which is worse
    than reporting nothing. The SHA is what makes the offline mode safe.

    Driven through the CLI rather than by importing `cached_root`. Two reasons,
    and the second is the one that decided it: `scripts/` holds loose modules
    rather than a package, so importing one needs either a `sys.path` poke that
    strict mypy cannot resolve or an `ignore_missing_imports` override that
    would make the helper `Any` and silently stop checking the calls under
    test. And the CLI is the surface the gate actually invokes, so this asserts
    the behaviour a gate depends on rather than an internal it happens to use.
    """
    workspace = tmp_path / "ws"
    root = workspace / "gson"

    if state == "not-a-checkout":
        root.mkdir(parents=True)
    elif state == "wrong-sha":
        root.mkdir(parents=True)
        subprocess.run(
            ["git", "-C", str(root), "init", "--quiet"], check=True, shell=False
        )

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--require-cached",
            "--only",
            "gson",
            "--workspace",
            str(workspace),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "NOT CACHED" in result.stdout, (
        f"a {state} workspace must not read as a cache hit: "
        f"{result.stdout}{result.stderr}"
    )
    assert "indexing" not in result.stdout, (
        f"a {state} workspace was indexed anyway, so the SHA check did not "
        f"gate it: {result.stdout}"
    )

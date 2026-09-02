"""The README's factual claims are derived from source, not maintained by hand.

**Nothing guarded `README.md` until now, and it drifted every time it was
touched.** On 2026-08-19 a rewrite found five stale figures and a wrong MCP tool
count; the ADR-0065 slices then hand-edited it four times and it drifted again
within a day -- the version line and the corpus counts were both wrong when
these tests were written, which is how they were mutation-checked.

The pattern this project keeps finding is that **a list which must be extended
when something is added, and which nothing enforces, is eventually wrong**:

* `SUPPORTED_FIXTURES` is guarded, and forced a decision every time.
* The findings and impact `ROWS` tables are guarded, and failed the gate.
* The PyInstaller data list was *not* guarded, and shipped an artifact that
  could not run at all.
* `README.md` was not guarded, and drifted twice in two days.

So these assertions read the same authorities a reader would have to check by
hand -- the version constants, the MCP registry, the corpus manifest -- and
compare them to the prose. They are deliberately narrow: they cover the facts
that have actually drifted, not the whole document, because a guard that fails
on ordinary rewording teaches people to delete it.

**When one of these fails, the README is usually the thing that is wrong.**

**Corrected 2026-08-21: the measured-results table is now partly guarded.**
This docstring used to argue the whole table was fine unguarded, because "the
figures in that table already name the artifact each came from so the check is
cheap by hand". That reasoning was tested by events and failed: the packaged
performance figures sat **eleven days stale** while the artifact was rebuilt
twice, and the ADR count was wrong from the day ADR-0067 landed. Both were found
by counting, not by anyone doing the cheap check. The two that are *derivable*
are now derived.

**The test count is guarded too, and the reasoning that once excused it was half
wrong.** This paragraph used to say the count could not be derived because it
comes from running the suite. Only *pass/fail* needs a run: `passed + skipped` is
the **collected** count, and collection is a pure function of the source. The
guard below collects in a subprocess and compares, so it fails only when the
count genuinely changes -- which is exactly when the README has gone stale --
rather than on every run, which was the other half of the old objection. The
number was hand-corrected three times before anyone tried deriving it.

**What remains deliberately unguarded.** Prose and structure: a guard that fails
on ordinary rewording is one people learn to delete.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from codeatlas.chunking.chunker import CHUNKER_VERSION
from codeatlas.contracts import CONTRACT_VERSION
from codeatlas.evaluation.dataset import load_dataset
from codeatlas.extraction.resolution import RESOLVER_VERSION
from codeatlas.mcp.tools import TOOL_SCHEMA_VERSION, build_registry
from codeatlas.parsing.registry import PARSER_BUNDLE_VERSION
from codeatlas.storage.sqlite.migrations import SCHEMA_VERSION

README = Path("README.md")
DATASET_ROOT = Path("tests/evaluation/cases")
ADR_DIRECTORY = Path("docs/adr")
PERF_ARTIFACT = Path("docs/evaluation/baseline-phase-7-perf.json")


def _readme() -> str:
    return README.read_text(encoding="utf-8")


# label -> (pattern capturing the stated value, the constant that declares it)
#
# Whitespace is `\s+`, never a literal space, and that is not style. Written
# with a literal space these patterns silently skip any claim the prose happens
# to wrap across a line: the README carried parser bundle `1.8.0` at line 335
# for two days, past a bump and past this guard, because "parser bundle" ended
# one line and `1.8.0` began the next. A guard that reads only the occurrences
# that fit on one line reports on the README's line breaks, not its claims.
VERSION_CLAIMS: list[tuple[str, str, str]] = [
    ("parser bundle", r"[Pp]arser\s+bundle\s+`([0-9.]+)`", PARSER_BUNDLE_VERSION),
    ("chunker", r"chunker\s+`([0-9.]+)`", CHUNKER_VERSION),
    ("resolver", r"resolver\s+`([0-9.]+)`", RESOLVER_VERSION),
    ("schema version", r"Schema\s+version\*\*\s+`([0-9]+)`", str(SCHEMA_VERSION)),
    (
        "contract version",
        r"\*\*Contract\s+version\*\*\s+\|\s+`([0-9.]+)`",
        CONTRACT_VERSION,
    ),
    ("MCP tool schema", r"MCP\s+tool\s+schema\*\*\s+`([0-9.]+)`", TOOL_SCHEMA_VERSION),
]


@pytest.mark.parametrize(
    ("label", "pattern", "declared"), VERSION_CLAIMS, ids=lambda v: str(v)[:24]
)
def test_a_version_the_readme_states_matches_its_constant(
    label: str, pattern: str, declared: str
) -> None:
    """Every version in the README is the one the code declares.

    These are the figures a reader most reasonably trusts and the ones most
    likely to go stale, because a version bump happens in one file and the
    README is a different file that nobody's test run opens.
    """
    found = set(re.findall(pattern, _readme()))
    assert found, (
        f"the README no longer states a {label}; "
        "update this guard or restore the claim"
    )

    assert found == {declared}, (
        f"README says {label} {sorted(found)}, the code declares {declared!r}. "
        "The code is the authority; update the README."
    )


def test_the_readme_tool_count_matches_the_registry() -> None:
    """The MCP tool count is counted, not transcribed.

    It read 21 for a day because the list was copied by hand and `trace_flow` --
    the one tool built from a loop rather than a literal `name=` -- fell out.
    """
    stated = re.search(r"\*\*(\d+) tools\*\*", _readme())
    assert stated, "the README no longer states a tool count"

    actual = len(list(build_registry().names))
    assert int(stated.group(1)) == actual, (
        f"README says {stated.group(1)} MCP tools, build_registry() has {actual}."
    )


def test_the_readme_corpus_counts_match_the_dataset() -> None:
    """Query, change and fixture counts come from the manifest.

    They move whenever the corpus grows, which in this project is often, and
    they are quoted in a table a reader uses to judge how much the numbers
    beside them are worth.
    """
    stated = re.search(
        r"\*\*(\d+) query cases, (\d+) change cases, (\d+) fixtures\*\*", _readme()
    )
    assert stated, "the README no longer states corpus counts in the expected form"

    dataset = load_dataset(DATASET_ROOT)
    actual = (
        len(dataset.query_cases),
        len(dataset.change_cases),
        len(dataset.fixtures),
    )
    assert tuple(int(g) for g in stated.groups()) == actual, (
        f"README says {stated.groups()} (query, change, fixtures); "
        f"the dataset has {actual}."
    )


def test_the_readme_adr_count_matches_the_directory() -> None:
    """The count of accepted ADRs is counted, not transcribed.

    It read 66 against 67 on disk, wrong from the day ADR-0067 landed and found
    a week later only because someone counted while adding ADR-0068. The
    template and the index are excluded; ADR-0049 is reserved-but-never-written,
    so numbering is not a proxy for the count and the files must be listed.
    """
    stated = re.search(r"(\d+) accepted records", _readme())
    assert stated, "the README no longer states an ADR count"

    actual = len(
        [
            path
            for path in ADR_DIRECTORY.glob("*.md")
            if path.name != "README.md" and not path.name.startswith("0000-")
        ]
    )
    assert int(stated.group(1)) == actual, (
        f"README says {stated.group(1)} accepted ADRs; {ADR_DIRECTORY} holds {actual}."
    )


def test_the_readme_performance_figures_match_the_tracked_artifact() -> None:
    """The packaged p95 figures come from the artifact that recorded them.

    These went stale for eleven days across two `PARSER_BUNDLE_VERSION` bumps
    while the README advertised a passing refresh target that the artifact
    already recorded as missed. The artifact is the authority; it is written by
    `measure_phase7_perf.py` and is the file the README's own source column
    names.
    """
    stated = re.search(
        r"\*\*([0-9.]+) s · ([0-9.]+) s\*\* \(semantic-local, on the artifact; "
        r"cold start ([0-9.]+) s",
        _readme(),
    )
    assert stated, (
        "the README no longer states packaged p95 figures in the expected form"
    )

    recorded = json.loads(PERF_ARTIFACT.read_text(encoding="utf-8"))
    actual = (
        recorded["refresh_p95_s"],
        recorded["preflight_p95_s"],
        recorded["cold_start_s"],
    )
    assert tuple(float(g) for g in stated.groups()) == actual, (
        f"README states {stated.groups()} (refresh p95, preflight p95, cold start); "
        f"{PERF_ARTIFACT} records {actual}."
    )


def test_the_readme_says_whether_the_refresh_target_is_met() -> None:
    """A missed target is stated as missed (`AGENTS.md` §19.3).

    The artifact carries `refresh_target_met`. When it is false the README must
    say so, because the figure alone reads as a result rather than as a miss --
    which is exactly how it read for eleven days.
    """
    recorded = json.loads(PERF_ARTIFACT.read_text(encoding="utf-8"))
    says_missed = "MISSES its ≤ 2 s target" in _readme()

    if recorded["refresh_target_met"]:
        assert not says_missed, (
            "the artifact records refresh_target_met true, but the README still "
            "declares the target missed."
        )
    else:
        assert says_missed, (
            "the artifact records refresh_target_met false; the README must say "
            "the target is missed rather than quoting the figure alone."
        )


def test_the_readme_test_count_matches_what_the_suite_collects() -> None:
    """The README's ``N passed, M skipped`` must equal what pytest collects.

    **Only pass/fail requires running the suite; the total does not.** A
    collected test either passes, fails, or is skipped, so ``passed + skipped``
    is the collected count for any green run -- and the README only ever quotes
    a green run. Collection is a pure function of the source, which is what
    makes this derivable at all, and deriving it is what stops the row going
    stale a fourth time.

    Collected in a **subprocess** rather than from this session, because the
    outer run may have selected a subset while the README quotes the whole
    suite. Asking the outer session would make the guard's verdict depend on how
    it was invoked.

    ``--basetemp`` is passed so ``conftest.pytest_configure`` returns early.
    Without it the nested run allocates a session directory and calls
    ``_prune_old_sessions``; that prune is age-based with 24-hour retention and
    could not touch a live session, but not creating the directory is cheaper
    than having to know that.
    """
    stated = re.search(r"\*\*(\d+) passed, (\d+) skipped\*\*", _readme())
    assert stated, "the README no longer states 'N passed, M skipped'"
    claimed = int(stated.group(1)) + int(stated.group(2))

    with tempfile.TemporaryDirectory(prefix="readme-collect-") as basetemp:
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "tests",
                "--collect-only",
                "-q",
                "--basetemp",
                basetemp,
                "-p",
                "no:cacheprovider",
            ],
            capture_output=True,
            text=True,
            check=False,
        )

    assert completed.returncode == 0, (
        "collecting the suite failed, so the count could not be checked: "
        f"{completed.stdout[-2000:]} {completed.stderr[-2000:]}"
    )
    collected = re.search(r"(\d+) tests? collected", completed.stdout)
    assert collected, (
        f"pytest reported no collected count: {completed.stdout[-2000:]}"
    )
    assert claimed == int(collected.group(1)), (
        f"README claims {stated.group(1)} passed + {stated.group(2)} skipped "
        f"= {claimed}, but the suite collects {collected.group(1)}. Re-run the "
        "gate and update the Tests row with the figures it prints."
    )

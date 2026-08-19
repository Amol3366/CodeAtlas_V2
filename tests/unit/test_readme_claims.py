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

**What is deliberately not guarded, and why.** The README's test count is a
*measurement* -- it comes from running the suite, not from reading source -- so
no assertion here can derive it, and one that hard-coded it would need editing
on every run. It was stale when these tests were written too, and was corrected
by hand. Prose, structure and the measured-results table are likewise unguarded:
a guard that fails on ordinary rewording is one people learn to delete, and the
figures in that table already name the artifact each came from so the check is
cheap by hand.
"""

from __future__ import annotations

import re
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


def _readme() -> str:
    return README.read_text(encoding="utf-8")


# label -> (pattern capturing the stated value, the constant that declares it)
VERSION_CLAIMS: list[tuple[str, str, str]] = [
    ("parser bundle", r"[Pp]arser bundle `([0-9.]+)`", PARSER_BUNDLE_VERSION),
    ("chunker", r"chunker `([0-9.]+)`", CHUNKER_VERSION),
    ("resolver", r"resolver `([0-9.]+)`", RESOLVER_VERSION),
    ("schema version", r"Schema version\*\* `([0-9]+)`", str(SCHEMA_VERSION)),
    (
        "contract version",
        r"\*\*Contract version\*\* \| `([0-9.]+)`",
        CONTRACT_VERSION,
    ),
    ("MCP tool schema", r"MCP tool schema\*\* `([0-9.]+)`", TOOL_SCHEMA_VERSION),
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

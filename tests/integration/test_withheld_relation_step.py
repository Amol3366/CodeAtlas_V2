"""A step whose evidence was dropped is withheld, not cited against nothing.

ADR-0057 gives a lexical answer relation paths, and each step must cite evidence
**the answer already returned** -- the chunk whose range contains the edge's
reference site. A step with no containing chunk is withheld.

**The Deferred Register carried that branch as unreachable.** Mutating it to
cite a fabricated id left the whole suite green, because in every corpus fixture
each edge lands inside a returned chunk. The reason is structural rather than
accidental: an outgoing edge's reference site is inside its own source symbol,
so it is always in that symbol's file -- and a module chunk spans the whole
file, so whenever the module is among the hits every edge in it is contained.

The row named the way in: *"a bounded result set or a chunk dropped by evidence
validation reaches it."* This is the second. `symbol_ids` comes from the search
**hits**, while `cited` comes from the evidence the builder actually emitted, and
those two sets come apart when a file is modified after it was indexed. Its
chunks then fail content-hash validation and are dropped, its symbols stay in
the hit list, and their edges have nothing left to cite.

**The corpus cannot express this**, and not for want of a case: every evaluation
fixture is read exactly as indexed, and nothing in the harness edits a tree
between indexing and querying. It takes a test that mutates the file on disk.

The behaviour is also the product's own trust contract -- "if a file changed
after indexing, CodeAtlas withholds the excerpt and says so rather than showing
content that no longer matches the claim" -- so this covers the withheld step and
the stale-evidence rule in one place.

**Mutation-checked, and it found a second defence worth recording.** Replacing
the withheld branch with a fabricated evidence id fails these tests -- but it
fails them inside `QueryResponse` validation, which raises *"relation step
references unknown evidence"*. So a fabricated citation is refused by the
contract model as well as by this branch, which is Section 4.1 holding at two
layers rather than one. That does **not** make the branch redundant: the
validator turns a bad citation into a 500, while the branch withholds the step
and returns the rest of a correct answer.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest

from codeatlas.application.container import ApplicationServices, build_services
from codeatlas.application.registration import RegisterRepositoryRequest
from codeatlas.contracts import QueryResponse
from codeatlas.retrieval.lexical import SearchRequest
from codeatlas.storage.sqlite.connection import connect
from codeatlas.storage.sqlite.migrations import apply_migrations

# `render` is called by `Reporter.emit`, so `telemetry` carries real outgoing
# edges whose reference sites sit inside this file -- the steps that must
# disappear once the file's evidence is dropped.
TELEMETRY_PY = '''"""Telemetry helpers for the collector."""


class Reporter:
    """Sends aggregated telemetry to the collector."""

    def emit(self, row: str) -> str:
        return render(row)


def render(row: str) -> str:
    return row.upper()
'''

# A second file matching the same query, left untouched. Without it the answer
# would be empty after the edit and the test could not tell "withheld the step"
# from "returned nothing at all".
NOTES_MD = "# Collector notes\n\nThe collector aggregates telemetry rows.\n"

QUERY = "collector telemetry"


@dataclass
class Harness:
    services: ApplicationServices
    connection: sqlite3.Connection
    repository_id: str
    root: Path


@pytest.fixture()
def indexed(tmp_path: Path) -> Iterator[Harness]:
    root = tmp_path / "telemetry"
    root.mkdir(parents=True, exist_ok=True)
    (root / "telemetry.py").write_text(TELEMETRY_PY, encoding="utf-8")
    (root / "notes.md").write_text(NOTES_MD, encoding="utf-8")

    with connect(tmp_path / "telemetry.sqlite") as connection:
        apply_migrations(connection)
        services = build_services(connection)
        repository = services.registration.register(
            RegisterRepositoryRequest(path=str(root))
        )
        services.indexing.index(repository.repository_id)
        yield Harness(services, connection, repository.repository_id, root)


def _search(harness: Harness) -> QueryResponse:
    return harness.services.search.search_text(
        SearchRequest(
            repository_id=harness.repository_id,
            query=QUERY,
            request_id="withheld-step",
        )
    )


def _steps(response: QueryResponse) -> list[str]:
    return [
        f"{step.source} {step.kind} {step.target}"
        for path in response.relation_paths
        for step in path.steps
    ]


def test_the_steps_are_present_while_the_file_still_matches_its_index(
    indexed: Harness,
) -> None:
    """Guard the guard.

    Every assertion below is about steps *disappearing*. If this fixture stopped
    producing them in the first place -- a chunker change, a resolution change --
    the withheld-branch test would pass for the wrong reason and stop testing
    anything.
    """
    response = _search(indexed)
    assert _steps(response), (
        "the fixture no longer yields any relation step, so the withheld-branch "
        "test below cannot distinguish withholding from emptiness"
    )
    assert any(
        item.file_path.endswith("telemetry.py") for item in response.evidence
    )


def test_a_step_is_withheld_when_its_only_containing_chunk_is_dropped(
    indexed: Harness,
) -> None:
    """The branch itself, reached through evidence validation.

    The file is edited after indexing, so its chunks fail the content-hash check
    and never reach the cited set -- while its symbols are still search hits.
    Their edges then have no containing chunk, and ADR-0057 says withhold.
    """
    before = _steps(_search(indexed))
    assert before, "precondition: the untouched tree yields steps"

    (indexed.root / "telemetry.py").write_text(
        TELEMETRY_PY + "\n# touched after indexing\n", encoding="utf-8"
    )

    after = _search(indexed)
    assert _steps(after) == [], (
        "steps survived their evidence being dropped, so they now cite a "
        f"region this answer did not return: {_steps(after)}"
    )
    assert "EVIDENCE_STALE_FILE_CONTENT" in after.warnings, (
        f"the answer withheld the steps without saying why: {after.warnings}"
    )


def test_the_untouched_file_still_answers(indexed: Harness) -> None:
    """Withholding is per-step, not a whole-answer failure.

    The trust contract is that stale evidence is withheld *and said so*, while
    everything still valid is returned. An answer that collapsed entirely would
    satisfy the assertion above for the wrong reason.
    """
    (indexed.root / "telemetry.py").write_text(
        TELEMETRY_PY + "\n# touched after indexing\n", encoding="utf-8"
    )
    response = _search(indexed)

    cited = {item.file_path for item in response.evidence}
    assert any(path.endswith("notes.md") for path in cited), (
        f"the valid file stopped being cited too: {sorted(cited)}"
    )
    assert not any(path.endswith("telemetry.py") for path in cited), (
        "the edited file is still cited, so its content no longer matches the "
        "claim it supports"
    )

"""A `-Semantic` artifact has gone stale twice; this is the third defence.

The first two were instance fixes. DR-01b built the second real guard --
`test_tracked_artifact_metric_keys.py` -- which catches a *schema* drift with no
extras installed, and both recorded incidents had exactly that signature: two
added metric keys, no value change.

**It cannot catch the next one.** DR-06 added the `delivery_scheduler` fixture
and four semantic cases, which changes what these artifacts should *say* while
leaving their key set entirely correct. Nothing fails until somebody installs
torch and opts in, which is what "opt-in" means and why the row kept reopening.

So the artifact now records the digest of the corpus it was measured on, and
this test asserts the stamp still matches the corpus on disk. It imports no
optional extra and touches no model, so it runs in **every** gate -- which is
the whole point, and is why the register's proposed remedy (make `-Semantic`
mandatory) was refused: that would make the deterministic gate depend on torch,
the exact regression gate condition 2 exists to catch (ADR-0078).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from codeatlas.evaluation.dataset import dataset_inputs_digest

SEMANTIC_ROOT = Path("tests/evaluation/semantic_cases")
ARTIFACTS = (
    Path("docs/evaluation/baseline-phase-7.json"),
    Path("docs/evaluation/rerank-phase-7.json"),
)


@pytest.mark.parametrize("artifact", ARTIFACTS, ids=lambda path: path.name)
def test_the_artifact_was_measured_on_the_corpus_now_on_disk(artifact: Path) -> None:
    payload = json.loads(artifact.read_text(encoding="utf-8"))
    stamped = payload["corpus"]["inputs_digest"]
    assert stamped == dataset_inputs_digest(SEMANTIC_ROOT), (
        f"{artifact} was measured on a different semantic corpus than the one "
        "on disk. Regenerate it with `check_phase7.ps1 -Semantic` and review "
        "the diff (ADR-0022). Do not edit the digest: it is the record of what "
        "was measured, not a value to be brought into line."
    )


def test_the_digest_covers_fixture_content_and_not_only_the_case_files() -> None:
    """A fixture edit changes what the right answer is, so it must move it.

    Hashing only `dataset.json` and the case files would leave exactly the
    DR-06 hole open: a new fixture file changes every semantic answer while the
    manifest's counts and the case list can stay untouched.
    """
    before = dataset_inputs_digest(SEMANTIC_ROOT)
    victim = next(
        path
        for path in sorted((SEMANTIC_ROOT / "fixtures").rglob("*.py"))
        if path.is_file()
    )
    original = victim.read_bytes()
    try:
        victim.write_bytes(original + b"\n# probe\n")
        assert dataset_inputs_digest(SEMANTIC_ROOT) != before, (
            "a fixture edit left the digest unchanged, so the guard would not "
            "notice the corpus that decides the answers moving"
        )
    finally:
        victim.write_bytes(original)
    assert dataset_inputs_digest(SEMANTIC_ROOT) == before


def test_the_digest_separates_a_path_from_the_content_that_follows_it(
    tmp_path: Path,
) -> None:
    """Two corpora differing only in where a boundary falls must not agree.

    Without a separator, `ab` + `c` and `a` + `bc` hash identically. That is
    the classic concatenation collision, and it would let a rename that moved
    bytes across the path/content boundary pass as unchanged.
    """
    first = tmp_path / "first"
    (first / "pkg").mkdir(parents=True)
    (first / "pkg" / "ab.py").write_bytes(b"c")

    second = tmp_path / "second"
    (second / "pkg").mkdir(parents=True)
    (second / "pkg" / "a.py").write_bytes(b"bc")

    assert dataset_inputs_digest(first) != dataset_inputs_digest(second)

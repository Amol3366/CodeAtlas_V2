"""The corpus can finally express an ADR-0044-shaped defect.

Until now `predict_changes` compared two `DirectoryStateView`s, so
`GitBlobStateView` -- the view a real working-tree preflight reads its base
through -- never ran under the corpus at all. The Deferred Register recorded why
a case could not simply be added: **both directory sides apply the same ignore
rules**, so a tracked-but-ignored file is absent from each of them, and a case
asserting "no `SYMBOL_DELETED`" would pass with ADR-0044's fix *and* with it
reverted. Permanent green reads as coverage.

`ChangeCase.base_view` closes that. A `git_blob` case commits its base state and
reads it back through Git, against the target on disk -- one working tree, two
states, which is the shape `analyze_working_tree` actually uses.

**c033 discriminates, and that is the whole point of it.** Measured both ways by
removing the ignore filter from `GitBlobStateView.list_files`:

* with ADR-0044's fix -- changed `['capture']`, findings `['RETURN_VALUE_CHANGED']`
* without it -- changed `['bundled_total', 'capture']`, findings
  `['SYMBOL_DELETED', 'RETURN_VALUE_CHANGED']`

The fixture's `coverage/report.py` is tracked at HEAD and matched by the
`coverage/` ignore default. `coverage/` was chosen over the more obvious
`dist/`: this repository's own `.gitignore` excludes `dist/`, so a fixture file
under it could not be committed here -- the same collision between a fixture's
needs and an ignore default that ADR-0049 had to resolve for `git_changes`.
"""

from __future__ import annotations

from pathlib import Path

from codeatlas.evaluation.dataset import ChangeCase, load_dataset

DATASET_ROOT = Path("tests/evaluation/cases")


def _case(case_id: str) -> ChangeCase:
    dataset = load_dataset(DATASET_ROOT)
    return next(case for case in dataset.change_cases if case.id == case_id)


def test_every_change_case_declares_which_view_reads_its_base() -> None:
    """`base_view` is total, so no case is silently one or the other."""
    dataset = load_dataset(DATASET_ROOT)
    views = {case.base_view for case in dataset.change_cases}
    assert views <= {"directory", "git_blob"}


def test_exactly_one_case_reads_its_base_through_git() -> None:
    """Derived, so a second git-backed case has to be a deliberate addition.

    Running Git costs a subprocess per case, and every other case is a pure
    directory comparison that needs none. Adding more is a decision, not a
    default.
    """
    dataset = load_dataset(DATASET_ROOT)
    git_backed = [c.id for c in dataset.change_cases if c.base_view == "git_blob"]
    assert git_backed == ["c033"]


def test_the_git_backed_case_declares_the_ignored_file_it_must_not_report() -> None:
    """The forbidden claims are the case's real assertion.

    Without ADR-0044's fix the engine reports `bundled_total` as deleted at high
    severity on a tree whose only edit is one return statement. The case says
    so, so the failure mode is named in the corpus rather than only in a record.
    """
    case = _case("c033")
    assert case.base_view == "git_blob"
    assert "bundled_total was deleted." in case.forbidden_claims
    assert case.expected_changed_symbols == ["capture"]


def test_the_ignored_file_is_absent_from_the_declared_snapshot() -> None:
    """It is tracked on disk and outside the index, which is the whole setup.

    If a future edit added `coverage/report.py` to the fixture's declared
    members, it would become an indexed file and the case would stop testing
    the disagreement it exists for.
    """
    dataset = load_dataset(DATASET_ROOT)
    fixture = next(f for f in dataset.fixtures if f.id == "tracked_ignored")
    members = {member for snapshot in fixture.snapshots for member in snapshot.members}
    assert members == {"src/service.py"}

    ignored = dataset.fixtures_root / fixture.root / "coverage" / "report.py"
    assert ignored.is_file(), (
        "the tracked-but-ignored file is gone, so the case no longer exercises "
        "the two views disagreeing about which files exist"
    )

"""Relation identity: stable across snapshots, distinct where it must be."""

from __future__ import annotations

from codeatlas.contracts import RelationKind
from codeatlas.domain.ids import relation_id


def test_relation_id_is_derived_and_deterministic() -> None:
    first = relation_id("sym_a", RelationKind.CALLS, "claim", 12)
    second = relation_id("sym_a", RelationKind.CALLS, "claim", 12)

    assert first == second
    assert first.startswith("rel_")


def test_an_unchanged_call_site_keeps_its_id_across_snapshots() -> None:
    """The property that makes relation reuse observable and Phase 4 diffs possible."""
    assert relation_id("sym_a", RelationKind.CALLS, "claim", 12) == relation_id(
        "sym_a", RelationKind.CALLS, "claim", 12
    )


def test_each_identity_input_changes_the_id() -> None:
    baseline = relation_id("sym_a", RelationKind.CALLS, "claim", 12)

    assert relation_id("sym_b", RelationKind.CALLS, "claim", 12) != baseline
    assert relation_id("sym_a", RelationKind.MAY_CALL, "claim", 12) != baseline
    assert relation_id("sym_a", RelationKind.CALLS, "settle", 12) != baseline
    assert relation_id("sym_a", RelationKind.CALLS, "claim", 13) != baseline


def test_two_identical_references_on_one_line_are_distinguished_by_part() -> None:
    """`f(f(x))` calls the same name twice on one line; both are real edges."""
    first = relation_id("sym_a", RelationKind.CALLS, "f", 12, part=0)
    second = relation_id("sym_a", RelationKind.CALLS, "f", 12, part=1)

    assert first != second


def test_field_boundaries_cannot_collide() -> None:
    """A separator-free hash would let adjacent fields blur into each other."""
    assert relation_id("sym_a", RelationKind.CALLS, "bc", 1) != relation_id(
        "sym_ab", RelationKind.CALLS, "c", 1
    )

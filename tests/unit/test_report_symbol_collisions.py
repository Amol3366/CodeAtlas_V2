"""The instrument ADR-0071's numbers were taken with, now committed.

ADR-0071 reports 1202 collision groups over five real repositories, 221
separated by signature and 981 left on the ordinal. Those numbers came from an
ad-hoc probe that was never committed, so no later task could reproduce them or
contradict them -- and DR-03 through DR-05 each have to prove a mechanism's
class falls to zero. This module tests the committed replacement.

**A collision is two symbols in one file sharing a qualified name and a kind.**
Grouping on the emitted ``symbol_id`` would report zero forever, because
``ensure_unique_symbol_ids`` has already made them distinct by the time
``parse`` returns.
"""

from __future__ import annotations

from pathlib import Path

from scripts.report_symbol_collisions import report_collisions


def test_a_java_overload_pair_is_one_group_separated_by_signature(
    tmp_path: Path,
) -> None:
    (tmp_path / "Gson.java").write_text(
        "class Gson {\n"
        "  void toJson(String s) {}\n"
        "  void toJson(int i) {}\n"
        "}\n",
        encoding="utf-8",
    )
    report = report_collisions(tmp_path)
    assert report.groups == 1
    assert report.separated == 1
    assert report.ordinal == 0
    assert report.by_language == {"java": (1, 1, 0)}


def test_a_scala_class_object_companion_is_left_on_the_ordinal(
    tmp_path: Path,
) -> None:
    """`class Other` and `object Other` both map to CLASS, so they collide.

    Neither declares parameters, so both yield `signature is None` (ADR-0071)
    and identity falls to document order.
    """
    (tmp_path / "Other.scala").write_text(
        "package p\nclass Other\nobject Other\n", encoding="utf-8"
    )
    report = report_collisions(tmp_path)
    assert report.groups == 1
    assert report.separated == 0
    assert report.ordinal == 1


def test_a_scala_trait_object_companion_does_not_collide_at_all(
    tmp_path: Path,
) -> None:
    """**ADR-0071 names the wrong pair, and this pins the correction.**

    ADR-0071 says a Scala companion `trait`/`object` pair collides and needs the
    declaration form to separate it -- 908 of the 981 groups it left on the
    ordinal. Measured here, a `trait` captures as `definition.interface` and an
    `object` as `definition.object`, which
    `languages/scala.py:_KIND_BY_CAPTURE` maps to INTERFACE and CLASS. Different
    kinds are different `symbol_id`s, so the pair never collided.

    The mechanism ADR-0071 proposes is still the right one -- it is `class`
    against `object` that needs it, not `trait` against `object`. What the 908
    actually are is re-derived by the census over scalaz, not assumed from here.
    """
    (tmp_path / "Thing.scala").write_text(
        "package p\ntrait Thing\nobject Thing\n", encoding="utf-8"
    )
    report = report_collisions(tmp_path)
    assert report.groups == 0
    assert report.by_language == {}

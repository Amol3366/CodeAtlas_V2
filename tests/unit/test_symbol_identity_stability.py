"""An id survives a same-named sibling being inserted above it.

``ensure_unique_symbol_ids`` disambiguates a collision group by signature and
then by **ordinal in document order**. The ordinal is what makes identity
fragile: insert another member of the same group above an existing one and the
existing one's ordinal shifts, its id changes, and a diff reports a symbol as
deleted and re-added when nothing about it changed.

ADR-0071 gave Java and Scala a signature, which fixes the case where the members
differ by parameter types. **ADR-0072 measured what that leaves**: 981 groups
over five real repositories, of which **845 are separated by the declaration
they sit inside** rather than by anything in their own parameter list --

- **Scala members**, 772. A ``trait`` and its ``object`` render the same
  qualified-name prefix, so ``Align.max`` declared in both collides. The parents
  do *not* collide; ADR-0071 said they did and that was wrong.
- **Java members**, 47. One method overridden in several enum-constant bodies or
  anonymous classes. These are *overrides*, so the signature is required to
  match and can never separate them.
- **Rust methods**, 21. ``Display::fmt`` and ``Debug::fmt`` declare
  byte-identical parameters and differ only by the enclosing ``impl``'s trait.
- **Go types**, 5. ``type key struct{}`` inside two different functions.

**A member is identified here by its ``content_hash``, and the first draft of
this module got that wrong.** It asserted that the set of ids seen before the
insertion was a subset of the set seen after -- which passes on the broken
code, because the ordinal scheme *reuses* the same id values and merely hands
them to different symbols. Every one of the five assertions passed before a
line of the fix existed. Two members of a group cannot be told apart by
qualified name or kind, so each body below is deliberately distinct and the
hash of that body is what follows a member across the edit.
"""

from __future__ import annotations

import pytest

from codeatlas.parsing.registry import ParseRequest, default_registry


def _ids_by_content(
    language: str, relative_path: str, source: bytes, name: str
) -> dict[str, str]:
    """Map each member's ``content_hash`` to its ``symbol_id``."""
    parser = default_registry().parser_for(language)
    assert parser is not None, f"no parser registered for {language}"
    result = parser.parse(
        ParseRequest(
            repository_id="stability",
            snapshot_id="stability",
            file_id="f",
            relative_path=relative_path,
            language=language,
            content=source,
        )
    )
    matched = {
        symbol.content_hash: symbol.symbol_id
        for symbol in result.symbols
        if symbol.qualified_name == name
    }
    assert matched, f"no symbol named {name!r} was emitted"
    return matched


_SCALA_BEFORE = b"""package p
trait Align { def max: Int = 11 }
object Align { def max: Int = 22 }
"""

_SCALA_AFTER = b"""package p
class Align { def max: Int = 33 }
trait Align { def max: Int = 11 }
object Align { def max: Int = 22 }
"""

_JAVA_BEFORE = b"""enum Policy {
  A { String translate(Field f) { return "aa"; } },
  B { String translate(Field f) { return "bb"; } };
  abstract String translate(Field f);
}
"""

_JAVA_AFTER = b"""enum Policy {
  Z { String translate(Field f) { return "zz"; } },
  A { String translate(Field f) { return "aa"; } },
  B { String translate(Field f) { return "bb"; } };
  abstract String translate(Field f);
}
"""

_GO_BEFORE = b"""package m

func First() { type key struct{ aa int }; _ = key{} }
func Second() { type key struct{ bb int }; _ = key{} }
"""

_GO_AFTER = b"""package m

func Zeroth() { type key struct{ zz int }; _ = key{} }
func First() { type key struct{ aa int }; _ = key{} }
func Second() { type key struct{ bb int }; _ = key{} }
"""

_RUST_BEFORE = b"""struct S;

impl std::fmt::Display for S {
    fn fmt(&self) -> () { let _aa = 1; }
}

impl std::fmt::Debug for S {
    fn fmt(&self) -> () { let _bb = 2; }
}
"""

_RUST_AFTER = b"""struct S;

impl std::fmt::Binary for S {
    fn fmt(&self) -> () { let _zz = 3; }
}

impl std::fmt::Display for S {
    fn fmt(&self) -> () { let _aa = 1; }
}

impl std::fmt::Debug for S {
    fn fmt(&self) -> () { let _bb = 2; }
}
"""

_CASES = [
    pytest.param(
        "scala", "Align.scala", _SCALA_BEFORE, _SCALA_AFTER, "Align.max", 2,
        id="scala-companion-members",
    ),
    pytest.param(
        # Three, not two: the `abstract` declaration is itself a member of the
        # group, alongside the two constant bodies that override it.
        "java", "Policy.java", _JAVA_BEFORE, _JAVA_AFTER, "Policy.translate", 3,
        id="java-enum-constant-bodies",
    ),
    pytest.param(
        "go", "local.go", _GO_BEFORE, _GO_AFTER, "key", 2,
        id="go-function-local-types",
    ),
    pytest.param(
        "rust", "s.rs", _RUST_BEFORE, _RUST_AFTER, "S.fmt", 2,
        id="rust-two-trait-impls",
    ),
]


@pytest.mark.parametrize(
    ("language", "relative_path", "before", "after", "name", "expected"), _CASES
)
def test_an_id_survives_a_same_named_sibling_inserted_above_it(
    language: str,
    relative_path: str,
    before: bytes,
    after: bytes,
    name: str,
    expected: int,
) -> None:
    original = _ids_by_content(language, relative_path, before, name)
    extended = _ids_by_content(language, relative_path, after, name)

    assert len(original) == expected, "the fixture no longer collides"
    assert len(extended) == expected + 1, (
        "the inserted sibling must add one member, or this test measures "
        "something other than what it claims"
    )

    moved = {
        content: (identifier, extended[content])
        for content, identifier in original.items()
        if content in extended and extended[content] != identifier
    }
    assert not moved, (
        f"{len(moved)} member(s) changed id when a sibling was inserted above "
        f"them; the ordinal is still carrying identity: {moved}"
    )


@pytest.mark.parametrize(
    ("language", "relative_path", "before", "after", "name", "expected"), _CASES
)
def test_every_member_of_a_group_keeps_a_distinct_id(
    language: str,
    relative_path: str,
    before: bytes,
    after: bytes,
    name: str,
    expected: int,
) -> None:
    """The discriminator must not merge what the ordinal kept apart.

    A discriminator returning one value for two members of a group hands
    identity back to the ordinal, and one returning ``None`` for both does the
    same. Both are silent, so distinctness is asserted rather than assumed.
    """
    ids = list(_ids_by_content(language, relative_path, after, name).values())
    assert len(set(ids)) == len(ids) == expected + 1


_SCALA_PARENTS_BEFORE = b"""package p
class Align { def a: Int = 1 }
object Align { def b: Int = 2 }
"""

_SCALA_PARENTS_AFTER = b"""package p
case class Align(x: Int)
class Align { def a: Int = 1 }
object Align { def b: Int = 2 }
"""


def test_a_companion_object_keeps_its_id_when_a_class_is_inserted_above() -> None:
    """The parents, which need their **own** form rather than an enclosing one.

    `class Align` and `object Align` both map to CLASS
    (`_KIND_BY_CAPTURE`), so they collide -- while `trait Align` maps to
    INTERFACE and never did, which is the pair ADR-0071 named and ADR-0072
    corrected. 114 of scalaz's remaining groups are these top-level parents,
    measured, and they have no enclosing declaration at all.

    **Two declarations of the same form still fall back to the ordinal**, and
    that is correct: nothing distinguishes `case class Align` from
    `class Align` except where they sit. The assertion is on the object.
    """
    before = _ids_by_content("scala", "A.scala", _SCALA_PARENTS_BEFORE, "Align")
    after = _ids_by_content("scala", "A.scala", _SCALA_PARENTS_AFTER, "Align")

    assert len(before) == 2, "the fixture no longer collides"
    assert len(after) == 3, "the inserted class must add a member"

    # Identify the object by parsing its declaration alone.
    solo = _ids_by_content(
        "scala", "A.scala", b"package p\nobject Align { def b: Int = 2 }\n", "Align"
    )
    (object_hash,) = solo.keys()
    assert object_hash in before and object_hash in after, (
        "the object's body hash must appear in both variants"
    )
    assert before[object_hash] == after[object_hash], (
        "the companion object's id moved when a class was inserted above it"
    )

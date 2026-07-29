"""Identity for the optional semantic layer.

Two things are being pinned here, and they fail in different ways.

An **embedding key** that is not content-addressed turns a one-symbol edit into
a whole-corpus re-embedding — blueprint 8.21, and the cost contract the phase
plan forbids breaking. The tests below state the exact inputs that must and
must not change it.

A **namespace ID** becomes a directory name under the vectors root. Its inputs
include a model ID, which arrives from settings — that is, from a human typing
into a text field, which is untrusted input by AGENTS.md Section 4.4. A
namespace ID that passed `../` through would write outside the approved root.
"""

from __future__ import annotations

import pytest

from codeatlas.domain.errors import PathSafetyError
from codeatlas.domain.ids import embedding_key, embedding_namespace_id


def test_the_same_content_and_model_produce_the_same_key() -> None:
    first = embedding_key("hash_a", "minilm", 384, "l2_v1")
    second = embedding_key("hash_a", "minilm", 384, "l2_v1")
    assert first == second
    assert first.startswith("emb_")


def test_changed_content_produces_a_different_key() -> None:
    """The whole point: only changed content is re-embedded."""
    assert embedding_key("hash_a", "minilm", 384, "l2_v1") != embedding_key(
        "hash_b", "minilm", 384, "l2_v1"
    )


@pytest.mark.parametrize(
    ("model_id", "dimensions", "normalization_version"),
    [
        ("other-model", 384, "l2_v1"),
        ("minilm", 768, "l2_v1"),
        ("minilm", 384, "l2_v2"),
    ],
)
def test_every_declared_input_participates_in_the_key(
    model_id: str, dimensions: int, normalization_version: str
) -> None:
    """A key that ignored any of these would compare vectors across models.

    Blueprint 4.7.6: never mix vectors from different embedding models or
    incompatible dimensions in one similarity space. Identity is the first
    place that rule is enforced.
    """
    baseline = embedding_key("hash_a", "minilm", 384, "l2_v1")
    assert embedding_key("hash_a", model_id, dimensions, normalization_version) != (
        baseline
    )


def test_a_namespace_id_is_readable_and_deterministic() -> None:
    """It names a directory a human will see, so it leads with a slug rather
    than being a bare digest."""
    namespace = embedding_namespace_id("all-MiniLM-L6-v2", 384, "l2_v1")

    assert namespace.startswith("all-minilm-l6-v2_384d_l2_v1_")
    assert namespace == embedding_namespace_id("all-MiniLM-L6-v2", 384, "l2_v1")


def test_a_conventional_org_slash_name_model_id_is_accepted() -> None:
    """Real model IDs look like this — the pinned default included. Rejecting
    the slash outright would leave the shipped provider unable to name its own
    namespace, which is exactly how this was found.
    """
    namespace = embedding_namespace_id(
        "sentence-transformers/all-MiniLM-L6-v2", 384, "l2_v1"
    )

    assert namespace.startswith("sentence-transformers__all-minilm-l6-v2_384d_l2_v1_")
    assert "/" not in namespace
    assert "\\" not in namespace


def test_the_slash_mapping_cannot_make_two_models_collide() -> None:
    """`org/name` and a literal `org__name` render the same slug. The appended
    digest is what keeps them in separate similarity spaces — sharing one is
    blueprint 4.7.6's error, and it would be invisible.
    """
    assert embedding_namespace_id("org/name", 384, "l2_v1") != (
        embedding_namespace_id("org__name", 384, "l2_v1")
    )


def test_namespaces_differ_when_the_similarity_space_differs() -> None:
    assert embedding_namespace_id("m", 384, "l2_v1") != embedding_namespace_id(
        "m", 768, "l2_v1"
    )
    assert embedding_namespace_id("m", 384, "l2_v1") != embedding_namespace_id(
        "m", 384, "l2_v2"
    )


@pytest.mark.parametrize(
    "hostile_model_id",
    [
        "../../etc/passwd",
        "..\\..\\windows\\system32",
        "a\\b",
        "..",
        ".",
        "../sibling",
        "org/../escape",
        "C:/absolute",
        "//server/share",
        "model\x00truncated",
        "  ",
        "",
        "\u202e" "gnp.exe",  # right-to-left override
    ],
)
def test_a_hostile_model_id_cannot_escape_the_vectors_root(
    hostile_model_id: str,
) -> None:
    """The model ID can be user input and the namespace is a directory name.

    Rejected outright rather than sanitised into something acceptable: quietly
    rewriting an attack into a plausible directory name hides that it ever
    arrived. A legitimate `org/name` is the one shape that passes, and it is
    rendered as a single segment.
    """
    with pytest.raises(PathSafetyError):
        embedding_namespace_id(hostile_model_id, 384, "l2_v1")


def test_a_hostile_normalization_version_is_rejected_too() -> None:
    with pytest.raises(PathSafetyError):
        embedding_namespace_id("minilm", 384, "../escape")


def test_dimensions_must_be_positive() -> None:
    """A zero-dimension namespace would be a similarity space with no space."""
    with pytest.raises(ValueError):
        embedding_namespace_id("minilm", 0, "l2_v1")
    with pytest.raises(ValueError):
        embedding_key("hash_a", "minilm", -1, "l2_v1")

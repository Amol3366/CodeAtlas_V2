"""Reciprocal-rank fusion over the deterministic and semantic channels.

Before this, `augment` appended semantic candidates after all deterministic
evidence and dropped any the deterministic half had already cited. A chunk both
channels found therefore kept its lexical position and gained nothing from the
agreement — the code's own comment said "the two channels finding the same
chunk is the point of fusing them" and then discarded exactly that.

The cost was measurable. On the Phase 7 conceptual corpus the semantic channel
ranked `OrderService.cancel` **8th** for s007 while the fused answer put it
16th, and ranked `shipping_for` **1st** for s003 while the fused answer put it
5th. Both were recorded as engine weaknesses; both were this.

RRF sums `1 / (k + rank)` across channels. It reads **ranks only, never raw
similarity scores**, which matters because a lexical BM25 score and a cosine
distance are not comparable quantities and combining them directly would invent
a number that means nothing.
"""

from __future__ import annotations

from codeatlas.application.rank_fusion import RANK_FUSION_K, fuse_ranks


def test_agreement_between_channels_beats_a_strong_single_channel_rank() -> None:
    """The property the whole record exists for.

    `b` is second in both channels and `a` is first in one only. Two seconds
    outweigh one first, which is what "the two channels agree" should mean.
    """
    assert fuse_ranks(["a", "b"], ["c", "b"]) == ["b", "a", "c"]


def test_a_chunk_found_by_one_channel_still_appears() -> None:
    """Fusion reorders; it must never drop a channel's findings."""
    fused = fuse_ranks(["a"], ["b"])

    assert set(fused) == {"a", "b"}


def test_ties_resolve_to_the_deterministic_order() -> None:
    """A tie must not be settled arbitrarily.

    `a` and `b` are symmetric — first in one channel, absent from the other —
    so their scores are equal. The deterministic channel wins, because when the
    evidence is indifferent the answer should be the one that does not depend on
    a model.
    """
    assert fuse_ranks(["a"], ["b"]) == ["a", "b"]
    assert fuse_ranks(["a", "b"], []) == ["a", "b"]


def test_an_empty_semantic_channel_leaves_the_order_untouched() -> None:
    """Subtraction-proof: removing the layer restores the exact prior answer.

    This is the same property the fusion suite tests end to end, asserted here
    on the ordering rule itself so a future change to the arithmetic cannot
    quietly break it.
    """
    deterministic = ["a", "b", "c", "d"]

    assert fuse_ranks(deterministic, []) == deterministic


def test_duplicates_within_one_channel_do_not_accumulate_score() -> None:
    """A channel returning the same chunk twice has not corroborated itself.

    Without this, a chunk listed twice by one channel would outrank a chunk
    both channels agreed on, and the metric would reward a retrieval bug.
    """
    assert fuse_ranks(["a", "a", "b"], ["b"]) == ["b", "a"]


def test_the_k_constant_damps_the_top_of_the_ranking() -> None:
    """k is why rank 1 does not dominate every other signal.

    Documented as a test rather than a comment because the value is the whole
    behaviour: at k=60 the gap between rank 1 and rank 2 is small enough that
    agreement can overcome it, which is the point. A k near zero would make
    this fusion behave like "whichever channel ranked it first wins".
    """
    assert RANK_FUSION_K == 60

    single_first = 1.0 / (RANK_FUSION_K + 1)
    both_second = 2.0 * (1.0 / (RANK_FUSION_K + 2))
    assert both_second > single_first

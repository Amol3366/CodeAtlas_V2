"""Combine two ranked retrieval channels into one order.

Reciprocal-rank fusion: an item's score is the sum of ``1 / (k + rank)`` over
every channel that returned it. Items no channel returned are absent; items one
channel returned keep a single term.

**Ranks only, never scores.** A BM25 score and a cosine distance are not
comparable quantities, and combining them directly would invent a number with
no meaning. Rank is the one thing both channels express in the same units,
which is why this method needs no per-channel calibration.

This module decides *order*. It does not decide derivation, and it cannot:
callers keep their own evidence objects and only reorder them, so a
`semantic_candidate` stays a candidate wherever it lands. That separation is
what keeps `AGENTS.md` Section 4.3 intact — a model score may not promote a
probabilistic candidate to deterministic evidence, and here it never touches the
label.
"""

from __future__ import annotations

from collections.abc import Hashable, Iterable

RANK_FUSION_K = 60
"""The damping constant, at the value the RRF literature settled on.

It sets how much a top rank is worth relative to agreement. Near zero, whichever
channel ranked an item first would win outright and fusing would be pointless;
very large, every rank would score alike and the order would become arbitrary.
At 60 the gap between rank 1 and rank 2 in one channel is smaller than the gain
from appearing second in both, which is the behaviour being bought.
"""


def fuse_ranks[T: Hashable](
    deterministic: Iterable[T], semantic: Iterable[T]
) -> list[T]:
    """Return one order over both channels, best first.

    Ties resolve to the deterministic channel's order. That is deliberate
    rather than incidental: when the evidence is indifferent between two items,
    the answer should be the one that does not depend on a model.

    A channel that lists the same item twice contributes one term for it. A
    channel has not corroborated itself by repeating, and scoring the repeat
    would let a retrieval defect outrank genuine agreement between channels.
    """
    ordered_deterministic = list(dict.fromkeys(deterministic))
    ordered_semantic = list(dict.fromkeys(semantic))

    scores: dict[T, float] = {}
    for channel in (ordered_deterministic, ordered_semantic):
        for rank, item in enumerate(channel, start=1):
            scores[item] = scores.get(item, 0.0) + 1.0 / (RANK_FUSION_K + rank)

    # `sorted` is stable, so building the candidate list deterministic-first
    # makes the tie rule fall out of the sort rather than needing a comparator.
    candidates = ordered_deterministic + [
        item for item in ordered_semantic if item not in set(ordered_deterministic)
    ]
    return sorted(candidates, key=lambda item: -scores[item])

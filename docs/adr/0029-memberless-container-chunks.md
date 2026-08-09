# ADR-0029: A container with no member symbols carries its body

- Status: accepted
- Date: 2026-08-10
- Decision owners: user/product and implementing agent
- Supersedes: none

## Context

s013 — *"What stages can an order move through?"* — expects `OrderStatus`, a
four-value enum. Neither retrieval channel found it. Both reached it only
through the containing `models.py` file chunk, which ADR-0028 recorded as an
open chunking question.

Extraction was not at fault: `OrderStatus` is extracted as a `CLASS` symbol at
lines 6–12, exactly the expected range, and it has its own chunk at those lines.
The chunk's indexed text was the problem, in full:

```text
PATH: src/orders/models.py
LANGUAGE: python
SYMBOL: OrderStatus
TYPE: CLASS
PARENT: src.orders.models
LINES: 6-12
CODE:
class OrderStatus(Enum):
```

`DRAFT`, `PLACED`, `SHIPPED`, `CANCELLED` and the docstring *"Where an order
sits in its lifecycle"* appear nowhere. **The literal answer to the question was
absent from the index**, so no ranking change could have retrieved it — which is
why ADR-0028's fusion work moved every other case and not this one.

The cause is a rule that is right for the case it was written for. A class chunk
is an outline: it names its members rather than repeating their bodies, because
each member is chunked separately and repeating them would index the same bytes
twice and make the container match every query its members match.

**An enum has no member *symbols*.** Its values are assignments, not methods, so
nothing extracts them and nothing else chunks them. The outline rule reduced the
symbol to its declaration line and the content went nowhere.

## Decision

**A container with no member symbols is not a container. It is a leaf, and
leaves carry their code.**

One condition in `CodeChunker._chunks_for_symbol`: the container path is taken
when the symbol is a container *and has members*. Otherwise the existing leaf
path runs, which carries the body and splits at statement boundaries if it
exceeds the character budget — no new size handling was written.

`CHUNKER_VERSION` moves **1.0.0 → 1.1.0**, its first change since Phase 2.
Chunk text and container identity both change, so existing snapshots are stale;
`indexing.py` already refuses a stale chunker version rather than mixing two
chunking rules inside one snapshot.

## Why not wire the docstring instead

The obvious alternative was to pass the symbol's docstring, since
`build_symbol_retrieval_text` already renders a `DOCSTRING:` line.

**That line is unreachable today.** `SymbolRecord` has no docstring field and
all four call sites pass `docstring=None`, so the parameter has never been wired
to anything. Supplying it means changing the parser, the domain record, and the
storage schema, and bumping `PARSER_BUNDLE_VERSION` as well.

Carrying the body picks the docstring up anyway — it is part of the body — so
the larger change buys nothing this defect needs. The dead `docstring` parameter
is left in place and recorded here rather than removed: it is the right seam if
docstrings are ever wanted on *member-carrying* containers too, where the body
is deliberately not indexed.

## Measured

Phase 7 conceptual corpus, semantic side:

| Metric | Before | After |
| --- | ---: | ---: |
| `symbol_recall_at_10` | 0.8571 | **0.9286** |
| `primary_evidence_recall_at_10` | 0.7333 | **0.8000** |
| `ndcg_at_10` | 0.7292 | **0.7530** |
| `mean_reciprocal_rank` | 0.6875 | 0.6977 |
| `containing_evidence_recall_at_10` | 1.0000 | 1.0000 |
| `exact` / `containing_evidence_rate` | 0.0563 / 0.1080 | 0.0605 / 0.1116 |

s013 retrieves `OrderStatus` at rank 7, having been absent entirely.

**Phase 7's conceptual corpus now reports `targets_met: true` with no unmet
targets on the semantic side, and the deterministic side still misses two**
(`containing_evidence_recall_at_10` 0.8667, `symbol_recall_at_10` 0.7143). The
gap between the two columns is what makes this genuine uplift rather than a
redefinition.

**That claim needs its history attached.** Three changes on 2026-08-09–10
produced it, and only two of them changed the engine: ADR-0027 corrected the
recall metric to ADR-0003's containment granularity (**no engine change**),
ADR-0028 fixed rank fusion, and this record fixed indexing. Citing "Phase 7
meets every target" without ADR-0027 would overstate what the engine does.

### The cost, stated

**The deterministic side got slightly worse**: `mean_reciprocal_rank`
0.3714 → 0.3619, `ndcg_at_10` 0.4557 → 0.4476, and its evidence rates dip
(0.0752 → 0.0741 exact, 0.1278 → 0.1259 containing). Enum bodies add text that
matches more queries, which dilutes lexical ranking marginally. It is a real
cost of indexing more content and it is not offset anywhere on that column.

### The corpus that cannot see this

`baseline-phase-3` and `baseline-phase-4` are **byte-for-byte unchanged**,
because the retrieval fixtures contain no enum and therefore no memberless
container. The change is surgical, but it also means the main accuracy corpus is
structurally blind to it — the same shape ADR-0016 recorded when the Phase 4
corpus could not see derivation-tiered test edges. Coverage for this rule lives
in unit tests, not in that corpus.

## Alternatives

**Index enum values as symbols.** Larger, and it changes what a symbol *is* —
`SymbolKind` has no member for an enum case, and adding one affects graph
traversal, impact analysis, and `test_gaps`. Disproportionate to a retrieval
defect.

**Always carry a container's body.** Rejected and pinned by a test. A class
whose members are chunked separately would then be indexed twice and would match
every query its members match, which is the problem the outline rule exists to
prevent.

**Include the docstring only.** Would fix the semantic signal and still leave
`DRAFT`/`PLACED`/`SHIPPED`/`CANCELLED` — the literal answer — unindexed.

## Consequences

- `CHUNKER_VERSION` 1.0.0 → 1.1.0. **Every existing snapshot must be re-indexed**
  to pick this up, and a stale one is refused rather than silently mixed.
- A memberless container's chunk identity moves from an outline hash to the
  symbol's content hash, so those logical chunks are retired and rebuilt on the
  next index. Ordinary chunk-reuse behaviour for every other symbol is unchanged.
- A module with no member symbols — an `__init__.py` of bare imports — now
  carries its body too. That follows from the same rule and is an improvement
  for the same reason, but it was not the motivating case and is not measured.
- `build_symbol_retrieval_text`'s `docstring` parameter remains unwired.

## Security and Privacy

None. Chunk text is built from the file's own bytes, as before, and stays
bounded by the existing character budget. No new data leaves the process.

## Migration and Rollback

No schema or contract change. `contract_version` stays `1.1`, `SCHEMA_VERSION`
stays `14`, `PARSER_BUNDLE_VERSION` and `RESOLVER_VERSION` are untouched.
Rollback is reverting the commit, restoring `CHUNKER_VERSION` to `1.0.0`, and
re-indexing; nothing persisted depends on the new text beyond the chunk rows
themselves.

## Approval

Approved by the user on 2026-08-10, who asked for the `OrderStatus` chunking
issue to be fixed after ADR-0028 recorded it as open. The corpus was **not**
edited (ADR-0003).

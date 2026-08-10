# ADR-0039: An `IMPORTS` edge targets the symbol the statement binds

- Status: accepted
- Date: 2026-08-10
- Decision owners: user/product and implementing agent
- Supersedes: none

## Context

ADR-0035 qualified the corpus's bare module names and **deliberately left q010
half-fixed**, recording why:

> Its source was qualified; its target was not. `from .idempotency import
> IdempotencyStore` — the corpus claims the edge targets the **module**, the
> engine records the **class** actually bound, and ADR-0021's import-and-call
> rule depends on the engine's reading. That is a modelling question, not a
> spelling, so q010 still scores 0 for one stated reason instead of two.

That question is settled here. The corpus declares:

```text
src.payments.service IMPORTS idempotency
```

and the engine emits:

```text
src.payments.service IMPORTS IdempotencyStore
```

**The decisive fact was not in ADR-0035's framing: q010 contradicts itself.**
Its `expected_symbols` are `["PaymentService", "IdempotencyStore"]` — the case
already declares the class as the answer to "What dependency does service
import?" Only its `expected_relations` string says `idempotency`. One case
asserts both readings.

That moves this out of ADR-0035's territory (an expectation the system cannot
satisfy) and into ADR-0031's (an expectation that disagrees with itself), which
is a stronger and more checkable justification.

## Decision

**An `IMPORTS` relation targets the symbol the import statement binds, not the
module it was reached through.** q010's expectation is corrected to name
`IdempotencyStore`.

Three reasons, in order of weight:

1. **ADR-0021 depends on this reading.** Its import-and-call rule requires the
   imported owner to be a **class**, never a module — precisely so that
   `import orders` cannot vouch for every symbol inside it. The ADR-0016
   invariant corpus caught that over-reach when ADR-0021's first
   implementation got it wrong, failing with "i001: Order was expected to
   remain a gap but was not reported". Re-pointing `IMPORTS` at the module
   would reopen the hole that corpus exists to keep closed.
2. **The statement binds a name.** `from x import Y` puts `Y` in the
   namespace, not `x`. An edge claiming otherwise describes something the code
   does not do.
3. **The case already agreed**, in `expected_symbols`. Correcting the relation
   string makes q010 internally consistent rather than imposing a new
   convention on it.

## Alternatives

**Re-point extraction at the module.** The corpus is right and the engine is
wrong. Rejected on reason 1: it reopens the ADR-0021 hole, and it is also far
larger than it looks — an extraction change, a `RESOLVER_VERSION` bump, and
every existing snapshot stale until re-indexed, to satisfy one string that the
same case contradicts elsewhere.

**Record both edges** — `IMPORTS` the module *and* `IMPORTS` the bound symbol.
Rejected: it doubles every import edge in the graph to preserve an ambiguity
nobody asked for, and impact expansion would then traverse module-level import
edges, which is the ADR-0021 over-reach arriving by another route.

**Leave q010 scoring zero.** The ADR-0035 position, correct while the question
was unexamined. Rejected now that it is examined: a case that contradicts
itself is a corpus defect, and leaving it produces a permanent, meaningless
zero that makes `relation_path_recall` unreadable.

## Consequences

`relation_path_correctness` **0.6364 → 0.7273** and `relation_path_recall`
**0.7273 → 0.8182**, q010 moving 0.0000 → 1.0000 on both. **No other metric
moved**, which is the signature a one-endpoint corpus edit should have; a
change to symbol resolution or an evidence rate would have meant something was
wired wrong.

ADR-0034's decomposition now has **one** cause left rather than two: q027 and
q029 emit no relation paths at all, because lexical intents do not populate
`relation_paths` though their edges are stored. That is a design decision and
remains open. `relation_path_recall` is still ungated (ADR-0038), and this is
why.

**No engine behaviour changed and no source file was touched.** This is a
corpus correction.

Cost recorded: the ruling makes `IMPORTS` targets *narrower* than a reader
might assume from the word. An import edge does not tell you which module a
symbol came from — that is `src.payments.idempotency`, reachable from the
target symbol's own file, not from this edge. Anyone wanting module-level
dependency structure must derive it, and that is the intended trade: the edge
records what the statement did.

`contract_version` `1.1`, `SCHEMA_VERSION` `14`, dataset contract `1.0`. No
migration, no version bump of any kind.

## Security and Privacy

None. A corpus expectation string.

## Migration and Rollback

No migration. `baseline-phase-3` and `-4` regenerated; the diff is the two
relation metrics and nothing else. `baseline-phase-0` is unchanged, because
null metrics are all zero. **`baseline-phase-1` and `-2` deliberately
untouched** as frozen history.

ADR-0036's validator was run **before** the edit (green, proving the corpus was
otherwise consistent) and after (green, proving the new name resolves through
`SymbolStore.find_exact`). Rollback is reverting one string.

## Approval

The ruling was put to the user on 2026-08-10 with both options and their
consequences stated, and the user selected the bound class. Recorded by the
implementing agent. No Section 25 item is triggered.

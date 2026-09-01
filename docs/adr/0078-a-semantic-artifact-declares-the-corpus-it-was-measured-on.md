# ADR-0078: A semantic artifact declares the corpus it was measured on

- Status: accepted
- Date: 2026-09-02
- Decision owners: user/product (asked for the remaining register rows to be
  planned and executed) and implementing agent
- Supersedes: none — it **refuses** the remedy the register row proposed and
  closes the row on a narrower finding
- Related: ADR-0022 (a gated artifact that stops reproducing is reviewed, not
  absorbed), ADR-0077 (DR-06 added the second semantic fixture), gate
  condition 2 (an installation without the optional extras behaves exactly as
  Phases 0-6), DR-01b (the key-set guard this sits beside)

## Context

`baseline-phase-7.json` and `rerank-phase-7.json` are `--check`ed only under
`check_phase7.ps1 -Semantic`, which needs the optional extras and is opt-in.
Every routine `-SkipSync` run stays green while they rot.

They have rotted **twice**, with an identical signature both times: two added
metric keys, no value change — `finding_count_correctness` on 2026-08-16 and
`changed_symbol_exact_cases` on 2026-09-02. Adding a field to the shared report
model updates every artifact a gate regenerates and silently orphans the ones it
does not reach. Both times `rerank-phase-7.json` was found only after fixing
`baseline-phase-7.json`.

DR-01b built `test_tracked_artifact_metric_keys.py`, which catches exactly that
signature with no extras installed. The register row was then left open with a
ruling attached: **should the `-Semantic` `--check` steps stop being opt-in?**

## Decision

**No — and the ruling as posed has no good answer. The row is closed on a
different finding.**

Two parts.

### 1. The proposed remedy is refused, with its reason

Gate condition 2 requires an installation without the optional extras to behave
exactly like Phases 0-6. `check_phase7.ps1` is shaped around this and says so in
its own header: if the semantic work ever made the deterministic gate depend on
torch, "this script would fail to run at all on a machine that never opted in,
which is precisely the regression the condition exists to catch".

Making the semantic block mandatory trades a real release guarantee for a
staleness check. That is a worse bargain than the staleness.

### 2. The defect the row was actually pointing at is narrower, and closes

The key-set guard covers both *recorded* incidents. What it cannot cover is an
artifact going stale because **its inputs moved**. ADR-0077 added the
`delivery_scheduler` fixture and four semantic cases — which changes what these
artifacts should *say* while leaving their key set entirely correct.

Inputs can be hashed **without installing anything**. `dataset_inputs_digest()`
hashes the manifest, the case files and every fixture byte, in sorted
repository-relative path order, and both generators stamp it at
`corpus.inputs_digest`. `test_semantic_artifact_inputs.py` asserts the stamp
matches the corpus on disk; it imports no optional extra and touches no model,
so it runs in **every** gate.

`run_phase7_rerank_ab.py` needed no change: its payload already copies
`dict(baseline["corpus"])`, so it inherits the stamp.

## Consequences

- A semantic-corpus edit without a regeneration now fails immediately, in every
  routine run, naming both artifacts. **Mutation-checked against the real
  scenario**: appending one line to `delivery_scheduler/src/scheduler/backoff.py`
  fails both, while `test_tracked_artifact_metric_keys.py` stays green — which
  is the proof that the new guard catches what the existing one cannot.
- Both artifacts gained exactly **one line** and **no metric value moved**.
- The digest is **not a security boundary** and is not claimed as one. The
  corpus is trusted local test data; the property wanted is coverage, not
  strength.
- A path/content separator is used so a rename moving bytes across that
  boundary cannot leave the digest unchanged — the classic concatenation
  collision, pinned by its own test.
- **The gate still cannot detect a semantic artifact whose values drift for a
  reason other than its inputs** — a model or library upgrade, say. That
  genuinely requires running the model, and it stays behind `-Semantic`. This
  ADR narrows the hole; it does not claim to close it, and saying so is the
  point of recording the limit here rather than letting a future reader assume
  the artifacts are fully guarded.

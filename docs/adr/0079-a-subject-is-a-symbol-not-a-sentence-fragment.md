# ADR-0079: A subject is a symbol, not a sentence fragment

- Status: accepted
- Date: 2026-09-03
- Decision owners: user/product and implementing agent
- Supersedes: none

## Context

The Deferred Register carried a row opened 2026-09-02 by DR-09's audit: *"A
question beginning with the word 'Trace' is not routed to the trace channel."*
RW-02 measured the surrounding shape and reported that widening the `TRACE`
rule "reaches 4 of the 63" fall-through cases.

The ruling asked for was: widen the trace rule. **Executing it disproved its
own premise, and found a different defect underneath.**

### Correction 1 — the figure is 1, not 4

Five corpus cases declare `TRACE_FLOW`. Four fall through to lexical. But only
**one of the four begins with the word "trace"**:

| Case | Question | Begins "trace"? |
| --- | --- | :---: |
| q003 | `What validates the capture key?` | no |
| q026 | `Where does the frontend load orders?` | no |
| q032 | `Trace order data from frontend to backend.` | **yes** |
| q035 | `What does strict mode do?` | no |
| q063 | `Trace the flow from mount.` | yes — already routes |

No `^trace` rule can reach q003, q026 or q035. They are the general
anchored-rule shape RW-02 itself identified — *every* rule in `_RULES` is
anchored at both ends and admits one trailing subject token — and that is a
different question from this row. **Widening trace reaches exactly one case.**

The 4 was never measured as "what widening reaches". It is the count of
`TRACE_FLOW` cases that fall through, which is a different quantity that
happens to share a denominator. This is the fifth time in this project's record
that a figure stated in a brief was an artifact of a neighbouring question.

### Correction 2 — widening that one case makes it worse

The brief's supporting evidence reads: *"On q032's own fixture the trace
channel returns top-1 `loadOrder` with both expected ranges contained."* True —
**and only when the channel is handed the corpus's declared subject**, which
`report_routing_fidelity.py` supplies deliberately (it reroutes intent and
"changes nothing else", because confounding channel with subject extraction
would make the delta unreadable).

A classifier has no declared subject. It has the question. Scored on q032's own
fixture, holding everything but the subject fixed:

| Subject the channel is handed | Ranked symbols | Expected found |
| --- | --- | --- |
| `loadOrder` — the corpus's declared subject | `loadOrder`, `get_order` | **both** |
| `frontend` — what `from X` extraction yields | — | **none** |
| `order data from frontend to backend` — the remainder | — | **none** |
| *today:* falls through to text | `loadOrder`, `frontend.ts` | `loadOrder` |

The expected entry point is `loadOrder`. **The string `loadOrder` does not
appear anywhere in the question.** No extraction rule can recover it, because
the information is not in the input. Routing q032 to the trace channel would
therefore move it from one of two expected symbols to zero — a strict
regression on the only case the change reaches.

### The defect found underneath

While checking the above, `classify("Trace the flow from mount.")` was observed
to return the subject **`mount.`**, with the trailing full stop. Every rule ends
`(?P<subject>\S+)\s*$`, and `\S+` is greedy about punctuation.

Measured on q063's own fixture:

| Subject | Ranked symbols |
| --- | --- |
| `mount.` — what `classify()` produced | **none** |
| `mount` — punctuation stripped | `mount`, `renderList` |

This is worse than a miss. The question reached the **correct** channel and the
channel then answered nothing, so a user sees an abstention with no way to know
a full stop caused it. It affects **all seven subject-bearing rules**, not just
trace: `who calls capture.`, `callers of capture.`, `dependencies of capture.`,
`tests for capture.`, `docs for capture.` all carried the same defect. All seven
new tests failed on the *target* with the *intent* already correct, which is
what establishes that the routing was never the problem.

The corpus never saw it, because `engine_adapter._query_term` feeds the declared
symbol and bypasses the classifier by design (Phase 1 measured resolution, not
question understanding, and said so).

## Decision

**Two decisions, ruled together because measuring one produced the other.**

1. **Trailing sentence punctuation is stripped from an extracted subject.**
   `.!,;:` only, from the end of the subject token, and only when a rule
   captured a `subject` group. A dot *inside* a token stays load-bearing, so
   `orders.py` and `A.b` are untouched. `rstrip(...) or subject` keeps a subject
   made entirely of punctuation from becoming empty.

2. **The `TRACE` rule is NOT widened.** Ruled, then declined on measurement,
   with the table above as the reason. A question beginning with the verb
   *should* reach the trace channel; it is declined because the channel cannot
   answer it without an entry point the question does not contain, and returning
   nothing is worse than the partially-correct lexical answer it replaces.

`RETRIEVAL_POLICY_VERSION` moves **5.3 → 5.4**. The module contracts this: a
stored run records which policy answered it, so changing the rules without
changing the version would make an old run appear to have been answered by rules
it never saw.

## Alternatives

- **Widen and accept the regression.** Rejected: it degrades the one case it
  touches, and §4.1 does not trade a correct partial answer for an empty one on
  principle alone.
- **Widen, and abstain when the entry point does not resolve.** Honest under the
  abstention contract and still scores zero on q032, while costing engine work
  in a closeout. Recorded as the option to revisit if trace phrasing is ever
  reported by a user.
- **Solve subject extraction properly** — resolve candidate tokens against the
  snapshot and choose one that exists. This is the only alternative that
  actually fixes the class. It is a feature with its own corpus and measurement,
  not a closeout item, and it is named here so it is not rediscovered as new.
- **Strip punctuation from the whole question before matching.** Rejected: it
  changes `GREETING`'s target, which is asserted to be the raw text, so it would
  trade one silent behaviour change for another.

## Consequences

Positive: five phrasings a user would actually type now resolve instead of
silently abstaining, across seven rules. The fix is four lines and cannot reach
any path where a rule captured no subject.

Negative: the general anchored-rule shape is untouched — `Where is
PaymentService defined?` still falls through — and this ADR does not claim
otherwise. The register row for the general routing gap stays open with its own
trigger.

No corpus metric moves, in either direction. The evaluation harness bypasses
`classify()`, so nothing it measures is a function of these rules; that is a
stated limit of the instrument, not evidence that the change is inert.

## Security and Privacy

None. No data movement, no trust boundary, no logging change. Subject text is
already treated as untrusted input and is not interpolated into FTS syntax.

## Migration and Rollback

No migration. `SCHEMA_VERSION` stays 14, `contract_version` stays `1.1`,
`PARSER_BUNDLE_VERSION` stays 1.9.0, chunker 1.1.0, resolver 1.5.0 —
**no reindex.** `RETRIEVAL_POLICY_VERSION` is a stamp on new runs and does not
invalidate a stored one. Rollback is reverting the four-line strip and the
version constant.

## Approval

Approved by the user 2026-09-03, in two steps. The widening was approved first
on the brief's stated figures; when execution disproved them, the corrected
measurement was put back to the user and the widening was **declined**, with the
punctuation fix retained. Scope approved: strip trailing sentence punctuation
from an extracted subject, bump the policy version, do not widen the trace rule.

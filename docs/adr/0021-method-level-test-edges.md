# ADR-0021: A Method Can Be Tested

- Status: accepted
- Date: 2026-08-09
- Decision owners: user (approved extraction-time, `static_resolved`, all three surfaces), implementing agent (record)
- Supersedes: none
- Extends: ADR-0004 (relation model), ADR-0016 (derivation-tiered test edges)

## Context

`_derive_test_edges` emits a `TESTS` edge where a test file both **imports** and
**calls** a target. The import is checked against the target symbol itself:

```python
if target not in imported_by_file.get(relation.file_id, set()):
    continue
```

A method is never imported — you import its class and call the method on an
instance. So **no method anywhere could ever carry a `TESTS` edge.** In Python
and TypeScript codebases, that is most of the code.

Three surfaces were wrong as a result, and only the first was on the backlog:

**1. `related_tests(method)` returned nothing.** Asking about
`PaymentService.capture` produced silence while the edge sat on
`PaymentService`.

**2. `test_gaps` reported every changed method as untested.** Measured on the
`python_app` fixture by running the real engine over two directory states:

```
changed symbols: ['PaymentService.__init__', 'PaymentService.capture']
test_gaps:       ['PaymentService.__init__', 'PaymentService.capture']
```

`capture` is called directly by `test_capture_uses_idempotency_store`. This is
the flagship feature — the thing ADR-0016 exists to make accurate — reporting a
false gap on the most common shape of Python test.

**3. The gap reason claimed a doubt the evidence had settled.**
`CALLED_NOT_IMPORTED` read "A test calls this name without importing it, so the
call may resolve to a different symbol." But `_Adjacency.build` drops anything
whose `resolution` is not `RESOLVED`, so every edge reaching that reason is
resolved by construction. The sentence asserted ambiguity that the stored edge
explicitly did not have.

The stored relation was there the whole time:

```
CALLS  test_capture_uses_idempotency_store -> PaymentService.capture
       static_resolved  hint='service'  resolution=RESOLVED
```

`static_resolved` sits **above** `high_confidence_heuristic` on the derivation
ladder. So CodeAtlas was accepting the weaker signal as coverage and rejecting
the stronger one.

## Decision

**1. Emit a `TESTS` edge when an imported class's method is called with a
resolved call.** Import-and-call is unchanged as a principle; it is applied at
the right granularity — the class is imported, the method is called.

**2. Derivation is `static_resolved`**, reporting how the edge was actually
established: a call the resolver resolved to that exact symbol. The direct rule
keeps `high_confidence_heuristic`.

**3. `_QUALIFYING_COVERAGE` widens to `{static_resolved,
high_confidence_heuristic}`.** Everything below stays a candidate, so ADR-0016's
rule — a weak edge explains a gap without closing it — is untouched.

**4. `CALLED_NOT_IMPORTED` says only what was checked**: the test calls this,
but neither it nor its owner is imported there, so import-and-call did not
qualify it.

**5. `RESOLVER_VERSION` 1.2.0 → 1.3.0.** Existing snapshots are stale until
re-indexed; `change_analysis.py` already refuses a stale resolver version rather
than silently mixing derivations.

### The constraint that shaped the rule

**The owner must be a `CLASS`, and the target a `METHOD`.** The first
implementation accepted any owner, which included modules — and the ADR-0016
invariant corpus caught it immediately:

```
i001: Order was expected to remain a gap but was not reported
i002: total was expected to remain a gap but was not reported
```

Those fixtures are deliberately written `import orders` + `orders.Order()`, with
a comment in `conftest.py` explaining that a module import names only the module,
so the strict pass cannot be satisfied accidentally. Treating a module as an
"owner" let one module import vouch for every symbol inside it — the blanket
promotion this product exists to refuse — and would have closed the two gaps
ADR-0016 was written to keep open.

A class is different in kind from a module: importing a class and calling its
method is the same import-and-call evidence, named one level down. A module
import is not evidence about anything it contains.

**The invariant corpus did exactly the job it was built for**, on the first
change that threatened the invariant, four weeks after it was written and
against an author who believed the change was safe.

## Consequences

`PaymentService.capture` is no longer a false gap; `PaymentService.__init__`
correctly still is (the test constructs the class, and no edge records a
constructor call).

| Metric | Before | After |
| --- | ---: | ---: |
| `exact_symbol_resolution` | 0.7436 | 0.7692 |
| `relation_path_correctness` | 0.2083 | 0.2917 |
| `abstention_correctness` | 0.8500 | 0.8750 |
| `symbol_recall_at_10` | 0.6667 | 0.6923 |
| `valid` / `exact_evidence_rate` | 0.6400 | 0.6316 |
| `containing_evidence_rate` | 0.7067 | 0.6974 |
| change-side metrics | unchanged | unchanged |

The evidence rates fall slightly for the ADR-0018 reason: more edges are
returned, and per ADR-0003 a call site rarely equals a gold definition range, so
the denominator grows faster than exact-span matches. Recall and span precision
must be quoted together.

The tracked ADR-0016 invariant artifact is **byte-for-byte unchanged**, which is
the evidence that this widened coverage without weakening the invariant.

Target remains unmet: **0.7692 against 0.98.**

### Not addressed

A constructor call (`PaymentService(...)`) records no edge to `__init__`, so
constructors remain gaps. That is arguably correct — the test exercises
construction, not necessarily `__init__`'s body — but it has not been decided,
only observed.

# ADR-0033: `exact_symbol_resolution` keeps 0.98, and the corpus is the limitation

- Status: accepted
- Date: 2026-08-10
- Decision owners: user/product and implementing agent
- Supersedes: none
- Related: ADR-0032 (the same arithmetic, the opposite conclusion, deliberately)

## Context

ADR-0032 found that `lexical_resolution`'s 0.90 required 8/8 and tolerated no
failures, and restated it as 1.0. It recorded a second instance of the same
illusion without acting on it:

**`exact_symbol_resolution` scores 27 cases against a 0.98 threshold, which
requires 27/27 and tolerates zero failures.** 27 cases can only produce

```text
27/27 = 1.0000    26/27 = 0.9630    25/27 = 0.9259    24/27 = 0.8889
```

and 0.98 falls between the first two. It reads like "one miss allowed on 27
cases" and is not. Both live baselines currently measure 1.0000, so the gate
passes either way.

## Decision

**Keep 0.98. Document the arithmetic at the constant, and pin it with tests.**

This is deliberately *not* the treatment ADR-0032 gave `lexical_resolution`, and
the difference is the point.

`lexical_resolution`'s 0.90 was an **internal provisional value**, invented in
ADR-0023 to "match the recall family rather than for the number it produces",
carrying no product meaning. Restating it as 1.0 cost nothing and made an
internal gate honest.

`exact_symbol_resolution`'s 0.98 is a **declared release target** in
`AGENTS.md` Section 19.3 — *"Exact symbol lookup on fixtures >= 98%"* — cited in
approved phase gates. It is a defensible product commitment that becomes
expressible the moment the corpus reaches roughly fifty cases: at 50, 0.98
requires 49 and tolerates one miss.

So the number is not wrong. **The corpus is too small to express it.**

Two alternatives were rejected for the same underlying reason:

- **Set the gate to 1.0 and leave Section 19.3 at 98%.** The implementation
  would then quietly disagree with the contract, which is exactly what ADR-0013
  refused: *"a contract is not amended by an implementation quietly disagreeing
  with it."*
- **Set the gate to 1.0 and amend Section 19.3 to 100%.** This tightens a
  *product promise* to match an artifact of corpus size — the instrument
  dictating to the authority it exists to measure. The product never promised
  zero exact-lookup misses in perpetuity.

**Being stricter than the declared target is safe.** Nothing violating 98% can
pass a 27/27 gate. The defect was never the strictness; it was that the
strictness was undocumented, so a reader met a number that misdescribed the
behaviour.

## Consequences

- No behaviour, metric, threshold, or baseline changes. Nothing is regenerated.
- The granularity is now stated where a reader meets the constant, rather than
  discovered by arithmetic.
- Two tests pin it. One asserts 0.98 tolerates no failures at 27 cases. The
  other **fails deliberately once the corpus grows enough for 0.98 and 1.0 to
  separate**, at which point the gate stops being stricter than its target and
  this record stops applying.
- **The real fix is corpus size**, and it is now a recorded open item rather
  than an implicit one. Growing the symbol-shaped corpus toward fifty cases
  would make Section 19.3's target mean what it says, and is separate work with
  its own considerations.
- `AGENTS.md` Section 19.3 is **not edited.** The target stands as written.

## Security and Privacy

None. A comment and two tests.

## Migration and Rollback

Nothing to migrate. No constant, artifact, or contract changed.

## Approval

Approved by the user on 2026-08-10, choosing to document and test rather than
restate the value, after the distinction from ADR-0032 was reported.

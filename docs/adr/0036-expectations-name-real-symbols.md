# ADR-0036: An expectation must name an identifier the engine can resolve

- Status: accepted
- Date: 2026-08-10
- Decision owners: user/product and implementing agent
- Supersedes: none
- Related: ADR-0031 and ADR-0035, which each found one instance of this by hand

## Context

Two records in two days found the same class of defect by investigation:

- **ADR-0031** — q019 declared `README.Health`, which names no symbol. Because
  `expected_symbols[0]` is also the query the harness issues, the engine was
  asked something unanswerable and its correct abstention scored as a miss.
- **ADR-0035** — relation endpoints declared as bare module names (`orders`,
  `client`, `service`) that likewise name nothing.

Both were found by reading output and following a hunch. Neither could have been
found by any metric, because a metric can only score what it is given: an
expectation naming a thing that does not exist produces a plausible-looking zero.

## Decision

**Assert, in the suite, that every `expected_symbols` entry, every
`query_subject`, and both endpoints of every `expected_relations` string resolve
through the engine's own `SymbolStore.find_exact`.**

Implemented as tests rather than a `validate` subcommand: the dataset validator
checks structure without indexing, and this needs the fixtures indexed. Six
fixtures index in under three seconds, once per module.

### The rule is "resolvable", not "equals a qualified name"

This distinction was got wrong while writing this record, and the first probe
reported seven failures that were mostly its own fault.

`find_exact` resolves through four tiers — qualified name, module-qualified
name, short name, then case-insensitive short name — so `orders` legitimately
resolves to `src.orders`. A validator demanding qualified names would have
rejected valid expectations and driven a corpus edit that made nothing more
correct. The first probe also split relation strings on whitespace, which
mis-parses `Order flow DOCUMENTS get_order`, since a document heading is a
symbol whose name contains a space.

Using the engine's own resolver is also what keeps the rule honest as the
resolver evolves: an expectation is valid exactly when the engine can resolve
it, by definition rather than by a second implementation that could drift.

## What it found immediately

**q024 still carried the old convention.** It declared `README.Sample Service`
and a relation `README DOCUMENTS service.port` — neither of which names a
symbol, both the convention ADR-0031 ruled against the day before.

I had applied that ruling by searching for `README.Health` specifically, rather
than for the convention, and missed this. **No metric would ever have caught
it:** q024's intent is `CONCEPTUAL`, which the adapter does not support, so it
is `measured=False` and excluded from every accuracy aggregate by ADR-0024.

Corrected to `Sample Service` for both, which completes the approved ruling
rather than making a new decision. **No baseline moved**, because an unmeasured
case feeds no metric — which is precisely why the defect survived.

## Mutation-checked

The three assertions passed on first run once q024 was corrected, so they were
verified by reintroducing the real historical defects: `README.Health` and
`orders EXPORTS Order`. Both fail the validator, which is the evidence it would
have caught by construction what took two investigations to find by hand.

A fourth test pins the resolver itself, asserting it rejects
`README.Sample Service` and an invented name while accepting `Sample Service` —
so the suite cannot silently degrade into a validator that approves everything.

## What this does not check

**That a resolvable name is the *right* answer.** That is what the evaluation
metrics are for. This rejects only references to things that do not exist, which
is the failure no metric can catch.

It also does not check `expected_evidence` paths or line ranges, or the
`change_cases`. Those are worth extending to and are not done here.

## Consequences

- The corpus can no longer reference a symbol the engine cannot resolve without
  the suite failing, in measured and unmeasured cases alike.
- Adding a fixture or renaming a symbol will fail these tests if an expectation
  goes stale, which is the intent.
- Cost is roughly three seconds of suite time, indexing six fixtures once.
- **The rule is enforced but not written into `AGENTS.md`.** It is a corpus
  hygiene property, not a product contract, and Section 19.2's fixture
  requirements already imply it.

## Alternatives

**A `validate` subcommand.** Rejected: `run_evaluation.py validate` checks
structure without indexing, and giving it an indexing dependency would make a
fast structural check slow for every caller.

**Assert against `qualified_name` only.** Rejected on evidence — it reports
false failures for every short-name reference, as the first probe did.

**Leave it to review.** Rejected: review missed it twice in two days, including
once by the author of the ruling being applied.

## Security and Privacy

None. Tests that index existing fixtures in a temporary directory.

## Migration and Rollback

No schema, contract, or version constant changes. The only corpus change is
q024, completing ADR-0031. Rollback is reverting the commit.

## Approval

Approved by the user on 2026-08-10, who asked for the validator after ADR-0035
recorded it as worth considering.

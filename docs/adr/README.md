# Architecture Decision Records

ADRs capture decisions that affect product scope, privacy, trust, compatibility,
security, persistence, deployment, or an established public contract.

## Workflow

1. Copy `0000-template.md` to the next four-digit number and a short slug.
2. Set status to `proposed`; describe context, decision, alternatives,
   consequences, migration/rollback, security/privacy effects, and approval.
3. Link supporting measurements or discovery evidence.
4. Obtain explicit user/product approval for decisions listed in `AGENTS.md`
   Section 25.
5. Set status to `accepted` only after approval. Implementation plans may then
   depend on it.
6. Never edit an accepted decision to change its meaning. Add a new ADR with
   status `supersedes ADR-NNNN`.

ADR timestamps use UTC dates. Rejected and superseded records remain for audit.

## Accepted records

| ADR | Decision | Phase |
| --- | --- | --- |
| [0001](0001-local-deterministic-modular-monolith.md) | Local-first deterministic modular monolith; SQLite as the system of record | 0 |
| [0002](0002-phase1-storage-and-migration-mechanism.md) | Storage layout and the explicit forward-only migration mechanism | 1 |
| [0003](0003-evidence-granularity.md) | Evidence granularity; the gate is measured on containing evidence, and the corpus is never edited to fit the engine | 3 |
| [0004](0004-relation-model-and-contract-additions.md) | Relation model, derivation classes, and the additive contract entries | 3 |
| [0005](0005-change-assurance-engine-design.md) | Change-assurance engine: state views, impact orientation, finding rules, risk ordering | 4 |
| [0006](0006-web-application-design.md) | Web application: persistence, streaming, sanitization, and evidence presentation | 5 |
| [0007](0007-freshness-and-hardening-design.md) | The watcher is a trigger, never an authority; recovery, backup, and packaging decisions | 6 |
| [0008](0008-accept-then-stream-message-submission.md) | Accept-then-stream message submission; `contract_version` 1.0 → 1.1 | 6 |
| [0009](0009-measured-semantic-uplift.md) | Optional semantic layer admitted: provider-neutral embeddings, LanceDB base/delta with SQLite membership authoritative, per-repository privacy governance, shadow migration, measurement-admitted rerank/explanation | 7 |
| [0010](0010-repository-scoped-embedding-namespaces.md) | Which similarity space answers is a per-repository pointer, not a global active flag; migration `0012` drops the one-active index and backfills existing databases | 7 (post-gate) |
| [0011](0011-configurable-embedding-models.md) | Embedding model identity is configurable through `.env`; namespace derivation keeps it safe, and a custom OpenAI model must declare its width | 7 (post-gate) |
| [0012](0012-governed-answer-provider-policy.md) | Answer generation writes prose over untouched claims and evidence; local `llama3.2:3b` is primary, the default is off, and the feature ships available rather than admitted | 7 (post-gate) |
| [0013](0013-ephemeral-session-mode.md) | Ephemeral sessions are opt-in and never the default; one injected database path makes indexing, embeddings, and storage fresh per run, and §8.2's persistence requirement is scoped to default mode | none (post-gate) |
| [0014](0014-per-repository-embedding-model.md) | The embedding model is a per-repository decision for the local provider; migration `0014` stores it, precedence is policy → `.env` → default, and a candidate model's width is measured rather than declared | none (post-gate) |
| [0015](0015-frontend-credential-entry.md) | The OpenAI API key is entered in Settings and stored in the Windows Credential Manager, machine-wide, precedence store → `.env`; no response carries the value or any part of it, and the resolved key is never published to `os.environ` | none (post-gate) |
| [0016](0016-derivation-tiered-test-edges.md) | `TESTS` is derivation-tiered — direct edges stay `high_confidence_heuristic`, fixture- and helper-mediated edges are `low_confidence_heuristic`; `CONSUMES_FIXTURE` is stored and citable but excluded from impact expansion, and a weak edge explains a `test_gaps` entry without ever closing it | none (post-gate) |
| [0017](0017-evaluation-fixture-gate-correction.md) | `SUPPORTED_FIXTURES` had been frozen since Phase 1, scoring 16 of 39 query cases as misses the engine never saw; widening it to every fixture but `malicious_unsupported` moved `exact_symbol_resolution` 0.3846 → 0.6154 and `abstention_correctness` 0.5250 → 0.7500, regenerating the two live baselines while Phase 1–2 stay frozen as history | none (post-gate) |

None is superseded. ADR-0008 is the first record to change a published contract
under Section 25, and carries that section's checklist as an explicit table.
ADR-0009 admits the optional vector store the blueprint gates behind its
activation approval, and records why no Section 25 item is triggered by
default.

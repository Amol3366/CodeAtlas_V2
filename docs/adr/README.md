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

None is superseded. ADR-0008 is the first record to change a published contract
under Section 25, and carries that section's checklist as an explicit table.

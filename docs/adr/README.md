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

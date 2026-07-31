# ADR-0010 — Repository-Scoped Embedding Namespaces

- Status: accepted
- Date: 2026-07-31
- Decision owners: user/product and implementing agent
- Supersedes: none
- Amends: ADR-0009 (measured semantic uplift), specifically the namespace model
- Related: `CLAUDE.md` Sections 4.2, 4.4, 16.1; migration `0012`;
  `docs/operations/semantic-search.md`

## Context

ADR-0009 decision 5 made the embedding provider a **per-repository** setting:
`none | local | openai`, default `none`, opt-in per repository. The settings API
enforces that scope — `GET/PATCH /v1/settings` require a `repository_id`, and a
call without one is refused rather than given an invented default.

The namespace model shipped in migration `0010` did not match that scope. It
carried a global uniqueness constraint:

```sql
CREATE UNIQUE INDEX embedding_namespaces_one_active
    ON embedding_namespaces (status)
    WHERE status = 'active';
```

with the comment "Exactly one namespace answers queries." That is a coherent
model for a single-repository product. It is not coherent alongside a
per-repository provider setting, and the two shipped together.

### The defect this produced

Found by code review on 2026-07-31, after the Phase 7 gate was approved, and
reachable entirely through the shipped API:

1. Repository A opts into `local`. `SnapshotEmbedder._ensure_namespace` creates
   namespace N1 (384-d) and marks it `active` — the first one always was.
2. Repository B opts into `openai`. `_ensure_namespace` finds an active
   namespace already exists and therefore creates N2 (1536-d) as **`shadow`**,
   because the unique index permitted nothing else.
3. B's embeddings are written into N2 — real vectors, real rows, no error.
4. `read_coverage` and `SemanticSearchService.search` both resolved the
   namespace with `NamespaceStore.get_active()`, which returned **N1**.

The observable results were all wrong and none of them was an error message
naming the cause:

- B's semantic coverage read **0% permanently**, because coverage was computed
  against a namespace B had never written to.
- Every semantic query for B embedded the query at 1536 dimensions and searched
  a 384-dimension space. The width check rejected it, and the caller reported
  `SEMANTIC_INDEX_UNAVAILABLE` — which says "nothing has been embedded yet"
  to a user whose content was fully embedded.
- Switching a *single* repository's provider produced the same outcome by the
  same path, so this was not limited to multi-repository installations.

Nothing in the settings flow routed the user to `EmbeddingMigrationService`,
which is the machinery that does handle changing models — and which was already
repository-scoped (`embedding_migrations.repository_id`, migration `0011`). The
inconsistency was therefore internal to Phase 7: migrations were per repository,
namespaces were global.

## Decision

**Separate the catalogue of similarity spaces from the choice of which space
answers for a repository.**

- `embedding_namespaces` remains **global**, one row per
  `(model_id, dimensions, normalization_version)`. This is deliberate and is
  not a compromise: embeddings are keyed by content hash, so two repositories on
  the same model share vectors, which is what makes the content-hash cache worth
  having across repositories and branches.
- `repository_namespaces` is **new** and per repository: `repository_id`
  (primary key) → `namespace_id`. This pointer is what `read_coverage`,
  `SemanticSearchService.search`, and the migration view consult.
- The global `embedding_namespaces_one_active` index is **dropped**. Two
  namespaces may now be `active` at once, because two repositories may be on
  different providers at once.
- `status` on a namespace keeps its meaning for the **migration lifecycle**
  (`shadow` while backfilling, `retired` after rollback). It is no longer what
  decides which space a query reads.
- `NamespaceStore.get_active()` survives for the migration lifecycle only, and
  its docstring says so. `get_for_repository()` is the correct lookup for
  anything answering a user's question.
- `_ensure_namespace` re-asserts the pointer on **every** index run, so
  switching a repository's provider retargets it on the next index rather than
  requiring a separate migration step for the ordinary case.
- Cutover and rollback in `EmbeddingMigrationService` now move the **pointer**
  for that migration's repository, not just the global status flag. Flipping
  status alone would have cut over nothing.

### The invariant did not disappear; it moved

The property worth protecting was never "one active namespace in the database".
It was **"a repository's results never mix vectors from two models"**, because
scores across embedding models are not comparable (`CLAUDE.md` Section 16.1:
"Never compare raw scores across embedding models"). A `PRIMARY KEY` on
`repository_namespaces.repository_id` enforces exactly that, per repository, and
is strictly more precise than the index it replaces.

## Migration and compatibility

Migration `0012` is forward-only and additive apart from the dropped index.
`SCHEMA_VERSION` 11 → 12. `contract_version` is **unchanged at `"1.1"`**: no
request or response shape changes.

Existing databases are backfilled. Any repository that had opted into a provider
was, by construction, being served by the single active namespace — there was no
other namespace it could have been using — so the migration points it there:

```sql
INSERT INTO repository_namespaces (repository_id, namespace_id, updated_at)
SELECT policy.repository_id, active.namespace_id, policy.updated_at
FROM repository_provider_policy AS policy
JOIN embedding_namespaces AS active ON active.status = 'active'
WHERE policy.embedding_provider <> 'none';
```

An upgraded database therefore keeps its existing vectors and coverage rather
than silently resetting to zero. A repository that had opted into nothing gets
no row, which is the correct representation of "not applicable".

## Consequences

**Good.** Multi-repository installations work with mixed providers. Coverage
tells the truth per repository. A provider switch is an ordinary supported
action. The scoping inconsistency between namespaces and migrations is gone.

**Costs and risks.** One more table and one more join on the retrieval path —
negligible, and indexed by primary key. `get_active()` remains callable and is
now a subtly wrong choice for most purposes; its docstring carries the warning,
and the two call sites that must not use it are the ones this ADR changed. Two
active namespaces are now legal, so the database no longer refuses a state that
was previously impossible — the protection moved into the pointer's primary key.

**What this does not change.** Deterministic retrieval is untouched and still
requires no provider. Snapshot membership remains the authority for which
vectors are eligible; the pointer decides *which space* is searched, never
*which rows* are valid.

## Alternatives considered

**Derive the namespace from the policy on every read.** The identity is a pure
function of `(model_id, dimensions, normalization_version)`, and the provider
constants are known without constructing a provider. Rejected: it still needs
the global unique index dropped to let a second namespace be `active`, so it
buys no simplification, and it would recompute a stored fact on every query
while losing the ability for a migration to point a repository at a namespace
its current policy does not name — which is exactly what a shadow cutover does.

**Make `embedding_namespaces` itself per repository.** Rejected: it would
duplicate a namespace row per repository per model and break vector reuse across
repositories, which is the point of content-hash keying.

**Leave it and document the limitation.** Rejected: the failure is silent. A
user sees 0% coverage and an "index unavailable" message that names the wrong
cause, with no path to a fix. A limitation the product cannot express to the
user is a defect.

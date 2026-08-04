# ADR-0014: The embedding model is a per-repository decision

- Status: accepted
- Date: 2026-08-04
- Decision owners: user/product and implementing agent
- Supersedes: none (extends ADR-0011)

## Context

ADR-0011 made embedding model identity configurable through `.env`, and its
reasoning still holds: the namespace is derived from `(model_id, dimensions,
normalization_version)`, so a configured model change starts a new similarity
space rather than mixing two.

What it left in place was an asymmetry the settings page made visible. The
*provider* was a per-repository decision stored in `repository_provider_policy`;
the *model* was a machine-wide `.env` value. The web settings page therefore
offered three provider radios and no model field at all. A user who wanted
`BAAI/bge-small-en-v1.5` had to find `.env`, know the variable name, and restart
the server — while `text-embedding-3-small` appeared to work out of the box.

The observed complaint was precise: the OpenAI model is effectively selectable,
and no open-source model is. Answer generation already had a model text input
(ADR-0012); embeddings did not.

Two facts about the code shaped what was possible. `resolve_local_embedding_model`
already documented that local model ids are safe to configure freely, because
the provider reads the true vector width from the model it loads. And
`build_embedding_provider(policy)` is the single choke point every caller
reaches, including the shadow-migration backfill via `ProviderFactory`.

## Decision

The embedding model is stored per repository, in the provider policy, for the
**local provider only**.

- Migration `0014` adds a nullable `embedding_model` column to
  `repository_provider_policy`. Null means "use the configured default for the
  chosen provider" — the convention migration `0013` established for
  `answer_model`.
- Resolution precedence is **policy → `.env` → pinned default**. A repository
  that never chose a model keeps following `.env`.
- The value is threaded through `build_embedding_provider`, so retrieval and
  the migration backfill resolve the model in one place.
- `POST /v1/models/embedding/validate` loads a candidate model and reports its
  **measured** vector width. The web client requires a successful check before
  enabling Save.
- A model id is refused for any provider other than `local`, checked against the
  resolved provider rather than the request.

OpenAI embedding model identity stays in `.env`, unchanged.

## Alternatives

**A curated dropdown of known models.** Fast and safe, but it is not "any model
you want": anything off the list would need a code change, which is the
complaint this record answers.

**One field covering OpenAI too.** Rejected for now. An unknown OpenAI id also
needs a declared width, because asking OpenAI for it costs a billable call per
construction (ADR-0011). That is a second input with a second failure mode, and
bundling it would have made the local case wait on it.

**Server-enforced validation.** Rejected as a guarantee that cannot be kept: the
API cannot verify that a caller ran the check first. Enforcing it in the client
and admitting that in the contract is honest; a server-side flag the client sets
would look like enforcement while being a client assertion.

**Keeping the model machine-wide and only improving the UI.** Rejected because
it contradicts Section 4.4's per-repository boundary — one repository could not
use a heavier model than another.

## Consequences

Positive: any sentence-transformers model is reachable from the settings page,
per repository, with its width measured rather than declared. Existing installs
are unaffected — an absent value resolves exactly as before.

Negative: a model change requires re-embedding, which is real work the user must
start. The first validation of an uncached model downloads its weights, so the
check can take minutes; the UI says so. `SCHEMA_VERSION` moves 13 → 14, so an
older build refuses a database written by this one — which is the intended
protection, not a regression.

`contract_version` stays `1.1`: one nullable column, one optional request field,
one additive endpoint.

## Security and Privacy

No new data movement. The local provider does not transmit, and the validate
endpoint carries only a model name — never repository content. A failed load is
reduced to a code before it reaches the client, because a provider message can
quote what produced it. No credential is involved: the field holds a model id.

The per-repository boundary is strengthened rather than weakened, since model
identity now sits behind the same policy row as the provider opt-in.

## Migration and Rollback

Forward: migration `0014` adds one nullable column. Verified by
`tests/integration/test_migrations.py`, which upgrades databases written at
versions 1, 4, 6, 7, and 9 and asserts no data loss.

Rollback of the *feature* for one repository: clear the model, which restores
the `.env` value. Rollback of a *model change*: the existing shadow-migration
cutover, which keeps the previous namespace serving until the new one is
complete and can be activated back.

Rollback of the schema is the standard path — restore the pre-migration
checkpoint written before any migration runs.

## Approval

Approved by the user on 2026-08-04, in the brainstorming session recorded at
`docs/superpowers/specs/2026-08-04-per-repository-embedding-model-design.md`.
Scope approved: per-repository storage, free-text entry with a validate step,
save-then-offer-migration on a model change, and local/open-source only.

# Per-repository embedding model selection

Date: 2026-08-04
Status: approved by the user, not yet planned or implemented
Related: ADR-0009 (semantic uplift), ADR-0011 (`.env` model identity),
ADR-0012 (governed answer providers), migration `0013` (answer model)

## Problem

A user can choose an embedding *provider* in the web Settings page, but not an
embedding *model*. The three provider radios are the whole surface: model
identity is resolved server-side from `.env` and rendered as read-only
descriptive text (`SemanticSettings.tsx:611`).

The result reads as an unfair asymmetry. `text-embedding-3-small` is shown as
the OpenAI model and works out of the box, while an open-source model cannot be
chosen at all from the UI — a user who wants `BAAI/bge-small-en-v1.5` has to
find `.env`, know the variable name, and restart the server. Answer generation
already has a model text input; embeddings do not.

Two facts about the current code shape the design:

- **Local model ids are safe to configure freely.** `resolve_local_embedding_model()`
  (`semantic/providers.py:159`) says so explicitly: the provider reads the true
  vector width from the model it loaded, so the namespace is derived from a
  measurement rather than a guess.
- **Model identity is global; provider choice is per repository.** The provider
  lives in `repository_provider_policy` in SQLite. The model comes from
  process-wide `.env`, and `EmbeddingMigrationService.start()`
  (`application/embedding_migrations.py:103`) builds its target namespace from
  that global config.

## Decisions

| Question | Decision |
| --- | --- |
| Where is the model stored? | Per repository, in the provider policy |
| How does the user enter it? | Free text, with a mandatory validate step |
| What happens on a model change? | Save immediately, then offer re-embedding |
| Does this cover OpenAI? | No — local/open-source only for now |
| The missing `semantic-local` extra? | The user installs it; the UI is unchanged |

## Design

### 1. Storage and domain

Migration `0014_embedding_model.sql`:

```sql
ALTER TABLE repository_provider_policy ADD COLUMN embedding_model TEXT;
```

Nullable, no default. `NULL` means "use the configured default for the chosen
provider" — the convention migration `0013` established for `answer_model`, and
what makes an existing database upgrade to exactly its current behaviour.

`RepositorySettings` gains `embedding_model: str | None`.

Resolution precedence becomes **policy → `.env` → pinned default**.
`resolve_local_embedding_model()` currently returns
`configured_local_model() or LOCAL_MODEL_ID`; it gains an optional policy value
ahead of those two. A repository that never chose a model keeps following
`.env`, so no existing install changes behaviour.

### 2. Model validation

New endpoint `POST /v1/models/embedding/validate`, modelled on
`POST /v1/models/ollama/pull`:

- Body: `{ "model_id": str }` (1–200 chars).
- Response: `{ provider, model_id, ok, dimensions, detail_code, latency_ms }`.

It constructs `LocalEmbeddingProvider(model_id=…)`, which loads the model and
reads its width through `_embedding_dimension()`. Failures return the standard
error envelope with a stable code; no stack trace and no filesystem path reaches
the client.

**Validation is a UI gate, not a server-side precondition.** The web client
requires a successful check before enabling Save; the API accepts any
syntactically valid model id, because it cannot verify that a caller validated
first and pretending otherwise would be a fake guarantee. A bad id therefore
fails at first embed with a provider error, which is the existing behaviour for
a misconfigured `.env` model and needs no new path. Leaving the field empty
means "use the default" and requires no validation at all.

The embedding namespace is keyed on
`(model_id, dimensions, normalization_version)`. A wrong width never raises — it
silently returns worse results indefinitely, which ADR-0011 already identifies
as the reason CodeAtlas refuses to guess. Measuring the model is the only safe
way to admit an arbitrary id, so the UI measures.

First validation of an uncached model downloads its weights. The endpoint needs
a generous timeout, and the UI must say that a download is happening.

### 3. Application services and adapters

`SettingsService.update()` gains `embedding_model: str | None` and a
`clear_embedding_model: bool` flag. The flag exists for the reason the budget
flags exist: `None` already means "not mentioned", and without it a caller
cannot express "remove the override".

The service rejects a model id when the selected provider is not `local`, so the
field cannot retain a stale value across a provider switch.

`SettingsResponse` and the update body gain `embedding_model`. Frontend API
types are regenerated with `scripts/generate_web_types.ps1`, never hand-edited.

`EmbeddingMigrationService._build_provider()` reads the model from the
repository policy instead of the global configuration. Without this change a
migration would backfill the *old* model into the new namespace — the one
genuinely dangerous failure in this feature, because it produces a namespace
whose label disagrees with its contents.

The CLI settings command gains a matching flag, keeping CLI, REST, MCP, and web
equal as Section 4.5 requires.

### 4. Web UI

In `SemanticSettings.tsx`, when the embedding provider is `local`, an "Embedding
model" panel appears in the existing right-hand aside, beside the answer-model
panel it mirrors:

- Text input; placeholder is the resolved default.
- A **Check model** button calling the validate endpoint, with its own pending,
  success, and error states.
- A result line reporting the detected dimensions, or the failure in plain
  language.
- Save is disabled until the typed id has validated in this session.

When the repository has an active namespace and the saved model differs from it,
a **Re-embed with the new model** action appears, driving the existing
shadow-migration endpoints: backfill into a new namespace, then atomic cutover
with rollback available. Semantic search keeps serving the old namespace until
cutover, and deterministic retrieval is unaffected throughout.

The panel follows `documentation/design.md`: existing tokens, no new component
library, status carried by text as well as colour, and no skeleton for data that
is not actually pending.

### 5. Testing

- **Unit** — resolution precedence (policy → env → pinned); update validation;
  rejection of a model id under a non-local provider; `clear_embedding_model`.
- **Storage/migration** — `0014` applies; a database written before it upgrades
  and keeps its behaviour.
- **Contract** — the new field round-trips through REST and CLI; the validate
  endpoint's success and failure branches.
- **Integration** — validation against a real small model; the migration service
  building a provider from the policy model.
- **Component** — field visibility per provider, save gating, error and pending
  states.

No existing test is deleted, skipped, or weakened. Nothing is reported as
passing that was not executed.

## Out of scope

- OpenAI embedding model selection. It keeps resolving from `.env` unchanged,
  because an unknown OpenAI id also needs a declared width and that is a second
  input with a second failure mode.
- A curated dropdown of known models.
- In-app installation of the `semantic-local` extra. A packaged build cannot
  mutate its own Python environment, and doing so is far more invasive than
  downloading a model file.
- Reranking models, answer models, and GPU device selection.

## Compatibility

`contract_version` stays `1.1`. Every change is additive: one nullable column,
one optional request field, one new endpoint. A client written before this
feature keeps working, and a repository that never sets a model behaves exactly
as it does today.

## Prerequisites

`uv sync --extra semantic-local` must be installed for the feature to be
exercisable at all. On the machine where this was designed it was not, which is
why the local provider reported `available: false` with
`requires: extra:semantic-local`.

## Governance

This changes the provider policy contract, so it needs **ADR-0014**, extending
ADR-0011's reasoning from a machine-wide `.env` value to a per-repository stored
one. ADR-0011 is not rewritten; it stays the record of the decision that was
made at the time.

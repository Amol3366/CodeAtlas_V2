# Semantic search and model providers

Phase 7 adds an optional semantic layer. The default remains `none`: exact
symbol lookup, lexical search, graph traversal, change analysis, conversations,
and packaging all work without torch, LanceDB, OpenAI, Ollama, or any model.

## Provider policy

Provider choice is per repository.

```powershell
codeatlas models --json
codeatlas settings <repository_id> --json
codeatlas settings <repository_id> --provider local
codeatlas settings <repository_id> --provider none
```

`local` uses the pinned `sentence-transformers/all-MiniLM-L6-v2` model and
transmits nothing. It requires the `semantic-local` extra in source runs and the
semantic package build for packaged runs.

`openai` is available only for embeddings and only through the governed provider
factory. Enabling it requires an explicit monthly token budget:

```powershell
codeatlas settings <repository_id> --provider openai --monthly-token-budget 50000
```

The settings and model APIs never return credentials. Provider telemetry records
provider, operation, request count, token estimate, latency, outcome, and time;
it has no columns for source text, prompts, evidence, answers, paths, or secrets.

## Choosing a local embedding model in Settings

A repository using the **local** provider chooses its own model, so one
repository can use a heavier model than another (ADR-0014).

Select "Local model" in Settings and an **Embedding model** field appears. Type
any sentence-transformers id — `BAAI/bge-small-en-v1.5`, `thenlper/gte-small`,
anything the library can load — then press **Check model**. Save stays disabled
until that exact id has been checked.

**Why the check is mandatory.** The vector namespace is labelled with the
model's width. A wrong width never raises an error; it silently returns worse
results for as long as the index lives. So CodeAtlas loads the model and
measures the width rather than trusting a typed number. The first check of a
model downloads its weights, which can take minutes.

The check is a client-side gate. `POST /v1/models/embedding/validate` accepts
any syntactically valid id, because the API cannot verify a caller checked
first, and a flag the client sets would be enforcement in name only. An id that
cannot load fails at first embed with a provider error — the same behaviour as a
misconfigured `.env` model.

Leaving the field blank means "use the configured default", and needs no check.
Precedence is **repository setting → `.env` → pinned default**. The CLI takes
the same setting on the same terms:

```powershell
uv run codeatlas settings <repository_id> --provider local --embedding-model BAAI/bge-small-en-v1.5
```

**Changing the model needs a re-embed.** Vectors from two models cannot share a
similarity space, so a saved model that disagrees with the namespace currently
serving search is not yet in effect. Settings offers **Re-embed with the new
model**, which drives the shadow migration described under *Model migrations*
below: the old namespace keeps answering until the backfill completes, and the
cutover is reversible.

OpenAI embedding model identity is **not** configurable per repository. It stays
in `.env`, because an unknown OpenAI model also needs a declared width that
cannot be measured without a billable call.

## Configuring credentials and models

### The API key, in Settings

The OpenAI API key can be entered in **Settings → OpenAI API key** and is
stored in the Windows Credential Manager, not in the database and not in a file
(ADR-0015). The field is write-only: no response ever returns the key or any
part of it, so the page reports only whether one is configured and where it
came from.

**Precedence is credential store → `.env`.** A key saved in Settings takes
effect immediately and outranks the file, and Settings says *"Configured from
.env"* when the file is what is actually in use — so a saved key being shadowed
is visible rather than a mystery.

**Clearing the key removes only the stored one.** `.env` is a file the user
owns, and CodeAtlas does not edit it.

**A backup does not carry the key**, because it is not in the database.
Restoring onto another machine or user account means entering it again.

On a platform with no credential store, Settings says so and `.env` is the only
route.

### Models, and the key without a UI (`.env`)

Copy `.env.example` to `.env` in the CodeAtlas project folder and edit it.
`.env` remains fully supported: it is what scripted and headless runs use, and
it is where OpenAI *model* identity is configured.

```ini
OPENAI_API_KEY=sk-...
# CODEATLAS_OPENAI_EMBEDDING_MODEL=text-embedding-3-small
# CODEATLAS_OPENAI_EMBEDDING_DIMENSIONS=1536
# CODEATLAS_LOCAL_EMBEDDING_MODEL=BAAI/bge-small-en-v1.5
```

**`.env` grants no permission.** It supplies a credential and model identity;
whether a repository may transmit is the per-repository setting above, stored
in SQLite. No variable can switch a repository from `none`.

**Where it is read from.** `$CODEATLAS_ENV_FILE` if set, otherwise `.env` in the
CodeAtlas root — the project folder in a source checkout, the folder beside
`codeatlas.exe` in a packaged build. The **current directory is never
searched**: running CodeAtlas from inside a repository you index must not let
that repository configure the tool. Use `CODEATLAS_ENV_FILE` when the install
folder is not writable.

**Precedence** for models is real environment > `.env` > pinned default, so
`set CODEATLAS_LOCAL_EMBEDDING_MODEL=... && codeatlas ...` overrides the file
for one command. For the *API key* the ladder starts one rung higher: a key
saved in Settings outranks both (ADR-0015).

**A custom OpenAI model must declare its width.** The vector namespace is
labelled with it, and CodeAtlas will not guess: set
`CODEATLAS_OPENAI_EMBEDDING_DIMENSIONS` alongside
`CODEATLAS_OPENAI_EMBEDDING_MODEL` or the provider refuses to build and names
the variable. `text-embedding-3-small` is 1536; `text-embedding-3-large` is
3072. The local provider needs no such setting — it reads the width from the
model it loaded.

Current behavior as of 2026-08-04: known OpenAI embedding model dimensions are
resolved automatically. `text-embedding-3-small` is 1536,
`text-embedding-3-large` is 3072, and `text-embedding-ada-002` is 1536. An
unknown OpenAI embedding model still must declare
`CODEATLAS_OPENAI_EMBEDDING_DIMENSIONS`. Local embedding dimensions are detected
from the model when it loads.

**Changing a model changes the namespace**, which is what makes it safe
(ADR-0011). Existing vectors are not reinterpreted; the new model starts an
empty namespace, and a model migration backfills it with rollback — see
[Model migrations](#model-migrations).

Env files are excluded from repository scans by default (`.env`, `.env.*`,
`*.env`), with `.env.example` still indexed. `.codeatlasignore` can override
that.

## Indexing and coverage

Embeddings are derived data. Deterministic snapshot activation never waits on
semantic usefulness, and a provider failure keeps the deterministic snapshot
usable.

Useful API checks:

```powershell
Invoke-RestMethod "http://127.0.0.1:8000/v1/repositories/<repository_id>/semantic-status"
Invoke-RestMethod "http://127.0.0.1:8000/v1/settings?repository_id=<repository_id>"
Invoke-RestMethod -Method Post "http://127.0.0.1:8000/v1/models/test?repository_id=<repository_id>"
```

For a repository with provider `none`, `/semantic-status` reports
`enabled=false` and `coverage=null`. For an enabled repository, coverage is tied
to the active snapshot and is complete only when every active unique content
hash has an embedded record in the namespace serving that repository.

Each repository is pointed at exactly one namespace, and repositories on
different providers keep separate ones (ADR-0010). Namespaces themselves
are shared across repositories on the same model, which is what makes the
content-hash cache reusable. Switching a repository's provider retargets it
on its next index.

## Retrieval behavior

Semantic retrieval is a discovery channel, not an authority. It is intent-gated
to conceptual text questions, fused with deterministic evidence, and every
candidate is validated against active SQLite snapshot membership before it can
appear in an answer. Exact symbols, callers, callees, dependencies, tests, docs,
and change analysis do not call the semantic provider.

The Phase 7 semantic baseline is recorded in
`docs/evaluation/baseline-phase-7.{json,md}`. It improved recall over the fixed
deterministic baseline, but still missed the Section 19.3 Recall@10 target.

## Model migrations

Embedding model changes use a shadow namespace:

```powershell
$migration = Invoke-RestMethod -Method Post `
  "http://127.0.0.1:8000/v1/models/embedding-migrations" `
  -Body '{"repository_id":"<repository_id>"}' `
  -ContentType "application/json"

Invoke-RestMethod "http://127.0.0.1:8000/v1/models/embedding-migrations/$($migration.migration_id)"

Invoke-RestMethod -Method Post `
  "http://127.0.0.1:8000/v1/models/embedding-migrations/$($migration.migration_id)/activate" `
  -Body '{"target":"target"}' `
  -ContentType "application/json"
```

The migration backfills the target namespace, keeps the current namespace active
until activation, dual-writes new content, and can roll back by activating the
source target. Raw scores are never compared across model namespaces.

## Reranking and explanations

P7-10 and P7-11 built the bounded seams and recorded admission decisions:

- Reranking: `docs/evaluation/rerank-phase-7.{json,md}` records `declined`.
  The only implemented reranker is `NoReranker`, an identity provider that
  performs no provider call and improves no metric.
- Explanation: `docs/evaluation/explanation-phase-7.{json,md}` records
  `declined`. The only implemented answer provider is `NoAnswerProvider`, which
  performs no provider call and produces no generated answer. Fake-provider
  tests cover evidence-only prompts and rejection of invalid generated claims.

Post-gate Ollama and OpenAI answer providers now exist behind repository-level
opt-in, redaction, budgets, timeouts, telemetry, and deterministic fallback.
Their presence does not change the Phase 7 admission record until a measured
uplift run admits them.

CodeAtlas does not download models. Settings names the answer model it expects
and shows the `ollama pull …` command for you to run in a terminal. A pull is a
slow, large network operation, and a failure inside a settings form reads as a
failed save rather than a failed download.

## Packaged semantic validation

The default package remains deterministic and small:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/build_package.ps1
```

The semantic-local package is explicit:

```powershell
uv sync --all-groups --extra semantic-local --frozen
powershell -ExecutionPolicy Bypass -File scripts/build_package.ps1 -SemanticLocal -SkipZip
uv run python scripts/measure_phase7_perf.py --json-output docs/evaluation/baseline-phase-7-perf.json
```

`measure_phase7_perf.py` refuses to substitute a deterministic-only measurement
when the semantic artifact, settings API, or local model is missing. A blocked
payload is a real result: it means the Phase 7 packaging/performance gate has
not been satisfied in that environment.

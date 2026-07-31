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
hash has an embedded record in the active namespace.

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

Concrete Ollama/OpenAI answer providers are not shipped. Adding them requires
the same repository-level opt-in, redaction, budgets, timeouts, telemetry, and
measured uplift before admission.

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

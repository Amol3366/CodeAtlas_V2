# Per-Repository Embedding Model Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a user choose any local (open-source) sentence-transformers embedding model per repository from the web Settings page, instead of only choosing a provider.

**Architecture:** One nullable `embedding_model` column on `repository_provider_policy`, following the `answer_model` convention that migration `0013` established. Resolution precedence becomes policy → `.env` → pinned default, threaded through the single choke point `build_embedding_provider(policy)`. A new validate endpoint loads a candidate model and reports its measured vector width, because the embedding namespace is keyed on that width and a wrong value degrades search silently.

**Tech Stack:** Python 3.12, SQLite, FastAPI, Pydantic v2, Typer, React 18 + TypeScript, TanStack Query, Vitest.

## Global Constraints

- `contract_version` stays `1.1`. Every change is additive.
- OpenAI embedding model selection is **out of scope**; it keeps resolving from `.env`.
- Type hints throughout Python; TypeScript strict, no `any`.
- Never hand-edit `apps/web/src/lib/api-types.gen.ts`. Run `scripts/generate_web_types.ps1`.
- No new dependency. `semantic-local` is an existing declared extra.
- Migrations are numbered and forward-only. The next free number is `0014` (the tree already has `0013`, despite `documentation/architecture.md` saying `0011`).
- Secrets never appear in a response, log, or diagnostic. The validate endpoint carries only a model name — never repository content.
- No test may be deleted, skipped, or weakened. Never report a test as passing that was not executed in this environment.
- Run from the repository root. Python: `uv run pytest …`. Web: `pnpm --dir apps/web …`.

## Prerequisite

`uv sync --extra semantic-local` must be installed before Task 4 and Task 7 can be exercised. Without it `sentence_transformers` is not importable, the local provider reports `available: false`, and the validate endpoint returns `PROVIDER_UNAVAILABLE`.

## File Structure

| File | Responsibility |
| --- | --- |
| `src/codeatlas/storage/sqlite/migrations/0014_embedding_model.sql` | **Create.** Adds the nullable column |
| `src/codeatlas/domain/semantic.py` | **Modify.** `ProviderPolicy.embedding_model` |
| `src/codeatlas/storage/sqlite/semantic_stores.py` | **Modify.** Persist and read the column |
| `src/codeatlas/semantic/providers.py` | **Modify.** Resolution precedence + validation helper |
| `src/codeatlas/application/settings.py` | **Modify.** `RepositorySettings`, `update()`, `validate_embedding_model()` |
| `src/codeatlas/api/routers/settings.py` | **Modify.** Contract fields + validate endpoint |
| `src/codeatlas/cli/main.py` | **Modify.** `--embedding-model` flag |
| `apps/web/src/lib/queries.ts` | **Modify.** Types + `useValidateEmbeddingModel` |
| `apps/web/src/features/settings/SemanticSettings.tsx` | **Modify.** The model panel |
| `docs/adr/0014-per-repository-embedding-model.md` | **Create.** The decision record |

---

### Task 1: Storage — the column and its round trip

**Files:**
- Create: `src/codeatlas/storage/sqlite/migrations/0014_embedding_model.sql`
- Modify: `src/codeatlas/domain/semantic.py:189` (after `answer_model`)
- Modify: `src/codeatlas/storage/sqlite/semantic_stores.py:385` (`set`), `:483` (`_policy_of`)
- Test: `tests/integration/test_migrations.py`, `tests/integration/test_settings_service.py`

**Interfaces:**
- Produces: `ProviderPolicy.embedding_model: str | None = None`, persisted and read back by `ProviderPolicyStore`.

- [ ] **Step 1: Write the failing test**

Add to `tests/integration/test_settings_service.py`:

```python
def test_embedding_model_round_trips_through_the_policy_store(connection) -> None:
    """A stored model id survives the write/read cycle.

    Null means "use the configured default", the convention `answer_model`
    established, so absence must stay distinguishable from a stored value.
    """
    from datetime import UTC, datetime

    from codeatlas.domain.semantic import EmbeddingProviderKind, ProviderPolicy
    from codeatlas.storage.sqlite.semantic_stores import ProviderPolicyStore

    store = ProviderPolicyStore(connection)
    store.set(
        ProviderPolicy(
            repository_id="repo-1",
            embedding_provider=EmbeddingProviderKind.LOCAL,
            monthly_token_budget=None,
            per_run_token_budget=None,
            updated_at=datetime.now(UTC),
            embedding_model="BAAI/bge-small-en-v1.5",
        )
    )

    assert store.get("repo-1").embedding_model == "BAAI/bge-small-en-v1.5"


def test_an_unset_embedding_model_reads_back_as_none(connection) -> None:
    from datetime import UTC, datetime

    from codeatlas.domain.semantic import EmbeddingProviderKind, ProviderPolicy
    from codeatlas.storage.sqlite.semantic_stores import ProviderPolicyStore

    store = ProviderPolicyStore(connection)
    store.set(
        ProviderPolicy(
            repository_id="repo-2",
            embedding_provider=EmbeddingProviderKind.LOCAL,
            monthly_token_budget=None,
            per_run_token_budget=None,
            updated_at=datetime.now(UTC),
        )
    )

    assert store.get("repo-2").embedding_model is None
```

Use the same `connection` fixture the surrounding tests in that file already use. Read the top of the file and match it exactly rather than inventing one.

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/integration/test_settings_service.py -k embedding_model -v`
Expected: FAIL — `TypeError: ProviderPolicy.__init__() got an unexpected keyword argument 'embedding_model'`.

- [ ] **Step 3: Write the migration**

Create `src/codeatlas/storage/sqlite/migrations/0014_embedding_model.sql`:

```sql
-- Which embedding model a repository uses, as its own per-repository decision.
--
-- Until now the provider was per repository but the model was machine-wide, in
-- `.env` (ADR-0011). That made an open-source model unselectable from the
-- settings page while the OpenAI default worked out of the box.
--
-- Null means "use the configured default for the chosen provider" — the same
-- convention `answer_model` uses one column over. That is what lets `.env` keep
-- setting a machine-wide default which a repository may override, without every
-- repository storing a copy of a value nobody chose, and it is why an existing
-- database upgrades to exactly its current behaviour.
ALTER TABLE repository_provider_policy
    ADD COLUMN embedding_model TEXT;
```

- [ ] **Step 4: Add the domain field**

In `src/codeatlas/domain/semantic.py`, directly after `answer_timeout_seconds: int | None = None` in `ProviderPolicy`:

```python
    # ``None`` means "the configured default for this provider", matching
    # ``answer_model``. Only meaningful for the local provider today; OpenAI
    # model identity stays in ``.env`` because an unknown OpenAI model also
    # needs a declared vector width (ADR-0011).
    embedding_model: str | None = None
```

- [ ] **Step 5: Persist and read the column**

In `src/codeatlas/storage/sqlite/semantic_stores.py`, in `ProviderPolicyStore.set`, extend the statement — add `embedding_model` to the column list, one more `?` to `VALUES` (nine total), and one more assignment to the `DO UPDATE SET` clause:

```python
            "INSERT INTO repository_provider_policy ("
            " repository_id, embedding_provider, monthly_token_budget,"
            " per_run_token_budget, updated_at, answer_provider, answer_model,"
            " answer_timeout_seconds, embedding_model"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"
            " ON CONFLICT (repository_id) DO UPDATE SET"
            " embedding_provider = excluded.embedding_provider,"
            " monthly_token_budget = excluded.monthly_token_budget,"
            " per_run_token_budget = excluded.per_run_token_budget,"
            " updated_at = excluded.updated_at,"
            " answer_provider = excluded.answer_provider,"
            " answer_model = excluded.answer_model,"
            " answer_timeout_seconds = excluded.answer_timeout_seconds,"
            " embedding_model = excluded.embedding_model",
```

and add `policy.embedding_model,` as the final element of the parameter tuple.

In `_policy_of`, add as the last argument:

```python
        embedding_model=row["embedding_model"],
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest tests/integration/test_settings_service.py tests/integration/test_migrations.py -v`
Expected: PASS, including the pre-existing migration tests — they assert the schema version, so confirm whether that file pins a migration count and update it if so.

- [ ] **Step 7: Commit**

```bash
git add src/codeatlas/storage/sqlite/migrations/0014_embedding_model.sql src/codeatlas/domain/semantic.py src/codeatlas/storage/sqlite/semantic_stores.py tests/integration/test_settings_service.py
git commit -m "feat: store a per-repository embedding model"
```

---

### Task 2: Resolution precedence — policy, then .env, then default

**Files:**
- Modify: `src/codeatlas/semantic/providers.py:159` (`resolve_local_embedding_model`), `:341` (`build_embedding_provider`)
- Test: `tests/unit/test_embedding_providers.py`

**Interfaces:**
- Consumes: `ProviderPolicy.embedding_model` from Task 1.
- Produces: `resolve_local_embedding_model(policy_model: str | None = None) -> str`.

**Divergence from the spec, deliberate.** The spec said `EmbeddingMigrationService._build_provider()` would be modified. It does not need to be: `_build_provider` defaults to `ProviderFactory(connection).build` (`application/embedding_migrations.py:96`), which delegates to `build_embedding_provider` for every non-OpenAI provider. Threading the policy value through this one choke point reaches the backfill path with no change to the migration service — which is better, because it removes the possibility of the two paths disagreeing about which model is current. Task 2's step 5 proves it by running the migration tests.

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/test_embedding_providers.py`:

```python
def test_the_policy_model_outranks_the_environment(monkeypatch) -> None:
    """A repository's own choice wins over the machine-wide default."""
    from codeatlas.semantic import providers

    monkeypatch.setattr(providers, "configured_local_model", lambda: "env/model")

    assert providers.resolve_local_embedding_model("repo/model") == "repo/model"


def test_the_environment_is_used_when_the_policy_is_silent(monkeypatch) -> None:
    from codeatlas.semantic import providers

    monkeypatch.setattr(providers, "configured_local_model", lambda: "env/model")

    assert providers.resolve_local_embedding_model(None) == "env/model"


def test_the_pinned_default_is_used_when_nothing_is_configured(monkeypatch) -> None:
    from codeatlas.semantic import providers

    monkeypatch.setattr(providers, "configured_local_model", lambda: None)

    assert providers.resolve_local_embedding_model(None) == providers.LOCAL_MODEL_ID
```

If `configured_local_model` is imported inside the function rather than at module scope, monkeypatch `codeatlas.settings.env_file.configured_local_model` instead. Check the import site before writing the test.

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/unit/test_embedding_providers.py -k model -v`
Expected: FAIL — `resolve_local_embedding_model() takes 0 positional arguments but 1 was given`.

- [ ] **Step 3: Add the parameter**

Replace `resolve_local_embedding_model` in `src/codeatlas/semantic/providers.py`:

```python
def resolve_local_embedding_model(policy_model: str | None = None) -> str:
    """Which sentence-transformers model the local provider loads.

    Precedence is policy, then ``.env``, then the pinned default. The
    repository's own choice wins because the provider decision is per
    repository (Section 4.4) and a machine-wide value cannot express "this repo
    uses a bigger model".

    Safe to configure freely: the provider reads the true width from the model
    it loaded, and the namespace is derived from that. A different model simply
    means a different namespace.
    """
    return policy_model or configured_local_model() or LOCAL_MODEL_ID
```

- [ ] **Step 4: Pass the policy value through the choke point**

In `build_embedding_provider`, change the local branch:

```python
    if kind is EmbeddingProviderKind.LOCAL:
        return _cached_local_provider(
            resolve_local_embedding_model(policy.embedding_model)
        )
```

`_cached_local_provider` is already keyed on the model id, so two repositories on different models get two cached providers rather than sharing one.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/test_embedding_providers.py tests/integration/test_embedding_migrations.py -v`
Expected: PASS. The migration tests matter here — they prove the backfill path picks up the policy model.

- [ ] **Step 6: Commit**

```bash
git add src/codeatlas/semantic/providers.py tests/unit/test_embedding_providers.py
git commit -m "feat: resolve the local embedding model from the repository policy"
```

---

### Task 3: Application service — update, clear, and reject

**Files:**
- Modify: `src/codeatlas/application/settings.py:49` (`RepositorySettings`), `:139` (`update`), `:457` (`_from_policy`)
- Test: `tests/integration/test_settings_service.py`

**Interfaces:**
- Consumes: `ProviderPolicy.embedding_model` (Task 1).
- Produces: `RepositorySettings.embedding_model: str | None`; `SettingsService.update(..., embedding_model: str | None = None, clear_embedding_model: bool = False)`.

- [ ] **Step 1: Write the failing test**

Add to `tests/integration/test_settings_service.py`:

```python
def test_a_local_repository_can_choose_its_embedding_model(service) -> None:
    result = service.update(
        "repo-1",
        embedding_provider=EmbeddingProviderKind.LOCAL,
        embedding_model="BAAI/bge-small-en-v1.5",
    )

    assert result.embedding_model == "BAAI/bge-small-en-v1.5"


def test_an_unmentioned_embedding_model_is_left_alone(service) -> None:
    """A partial update must not reset a field it never named."""
    service.update(
        "repo-1",
        embedding_provider=EmbeddingProviderKind.LOCAL,
        embedding_model="BAAI/bge-small-en-v1.5",
    )

    result = service.update("repo-1", per_run_token_budget=100)

    assert result.embedding_model == "BAAI/bge-small-en-v1.5"


def test_the_embedding_model_can_be_cleared_back_to_the_default(service) -> None:
    service.update(
        "repo-1",
        embedding_provider=EmbeddingProviderKind.LOCAL,
        embedding_model="BAAI/bge-small-en-v1.5",
    )

    result = service.update("repo-1", clear_embedding_model=True)

    assert result.embedding_model is None


def test_a_model_is_refused_for_a_provider_that_cannot_use_one(service) -> None:
    """Only the local provider takes a model id today.

    Storing one under `none` or `openai` would leave a value that looks
    effective and is not — the setting would appear to have been accepted while
    changing nothing.
    """
    with pytest.raises(InvalidRequestError):
        service.update(
            "repo-1",
            embedding_provider=EmbeddingProviderKind.NONE,
            embedding_model="BAAI/bge-small-en-v1.5",
        )
```

Match the existing fixture names in the file (`service`, or whatever it uses) instead of introducing new ones. Import `InvalidRequestError` from `codeatlas.domain.errors` if the file does not already.

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/integration/test_settings_service.py -k embedding_model -v`
Expected: FAIL — `update() got an unexpected keyword argument 'embedding_model'`.

- [ ] **Step 3: Add the field to the read model**

In `RepositorySettings`, after `answer_timeout_seconds`:

```python
    embedding_model: str | None = None
```

and in `_from_policy`, as the final argument:

```python
        embedding_model=policy.embedding_model,
```

- [ ] **Step 4: Extend update()**

Add two parameters to the `update` signature, after `answer_timeout_seconds`:

```python
        embedding_model: str | None = None,
        clear_embedding_model: bool = False,
```

Inside the method, after the `answer_timeout` resolution and before the transmitting-provider check:

```python
        model = _resolve(
            current.embedding_model, embedding_model, clear_embedding_model
        )
        if model is not None:
            model = model.strip()
            if not model:
                raise InvalidRequestError(
                    "An embedding model id cannot be blank. Omit it to use the"
                    " configured default.",
                    details={"field": "embedding_model"},
                )
            if len(model) > 200:
                raise InvalidRequestError(
                    "An embedding model id is limited to 200 characters.",
                    details={"field": "embedding_model"},
                )
            if provider is not EmbeddingProviderKind.LOCAL:
                # Checked against the resolved provider, not the request, so
                # switching away from `local` while a model is stored is caught
                # exactly like setting one under the wrong provider.
                raise InvalidRequestError(
                    "Only the local embedding provider takes a model id."
                    " OpenAI model identity is configured in .env, because an"
                    " unknown OpenAI model also needs a declared vector width.",
                    details={
                        "provider": provider.value,
                        "field": "embedding_model",
                    },
                )
```

Then add `embedding_model=model,` to the `ProviderPolicy(...)` construction.

`_resolve` already exists in this module and handles the three-way "unchanged / set / clear" question — read it before using it and confirm the argument order.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/integration/test_settings_service.py -v`
Expected: PASS, all tests in the file — including the existing budget and answer-provider ones.

- [ ] **Step 6: Commit**

```bash
git add src/codeatlas/application/settings.py tests/integration/test_settings_service.py
git commit -m "feat: accept a per-repository embedding model in settings"
```

---

### Task 4: The validate endpoint

**Files:**
- Modify: `src/codeatlas/application/settings.py` (new `validate_embedding_model`, beside `pull_ollama_answer_model` at `:368`)
- Modify: `src/codeatlas/api/routers/settings.py` (new body/response models and route, beside the pull route at `:239`)
- Test: `tests/contract/test_settings_api.py`

**Interfaces:**
- Consumes: `resolve_local_embedding_model` (Task 2).
- Produces: `SettingsService.validate_embedding_model(model_id: str) -> EmbeddingModelValidation` with fields `model_id: str`, `ok: bool`, `dimensions: int | None`, `detail_code: str | None`, `latency_ms: int`; endpoint `POST /v1/models/embedding/validate`.

- [ ] **Step 1: Write the failing test**

Add to `tests/contract/test_settings_api.py`:

```python
def test_validating_a_model_reports_its_measured_dimensions(client) -> None:
    """The width is measured, never guessed.

    The namespace is keyed on (model_id, dimensions, normalization_version). A
    wrong width never raises; it just returns worse results indefinitely, so
    the only safe way to admit an arbitrary model id is to load it and ask.
    """
    response = client.post(
        "/v1/models/embedding/validate",
        json={"model_id": "sentence-transformers/all-MiniLM-L6-v2"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["model_id"] == "sentence-transformers/all-MiniLM-L6-v2"
    if body["ok"]:
        assert body["dimensions"] == 384
    else:
        # Without the semantic-local extra installed there is nothing to load.
        assert body["detail_code"] == "PROVIDER_UNAVAILABLE"
        assert body["dimensions"] is None


def test_validating_rejects_a_blank_model_id(client) -> None:
    response = client.post("/v1/models/embedding/validate", json={"model_id": "  "})

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_REQUEST"
```

The branch on `body["ok"]` is deliberate: the gate environment may not have the extra, and a test that assumed it would fail for an environmental reason rather than a code one. Do not remove the branch to make the test look stricter.

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/contract/test_settings_api.py -k validat -v`
Expected: FAIL with 404 — the route does not exist.

- [ ] **Step 3: Add the service method**

In `src/codeatlas/application/settings.py`, add the result type beside `ProviderTestResult`:

```python
@dataclass(frozen=True)
class EmbeddingModelValidation:
    """Whether a candidate model loads, and how wide its vectors are.

    ``dimensions`` is the measured width, not a declared one. It is the field
    the whole endpoint exists for.
    """

    model_id: str
    ok: bool
    dimensions: int | None
    detail_code: str | None
    latency_ms: int
```

and the method on `SettingsService`:

```python
    def validate_embedding_model(self, model_id: str) -> EmbeddingModelValidation:
        """Load a candidate local model and report its true vector width.

        Not tied to a repository: this answers "could this model be used?",
        which is a question about the machine. Saving remains a separate,
        cheap SQLite write, exactly as it is for an Ollama pull.

        The first load of an uncached model downloads its weights, so this can
        take minutes. The request carries only a model name.
        """
        import time

        cleaned = model_id.strip()
        if not cleaned:
            raise InvalidRequestError(
                "An embedding model id is required.",
                details={"field": "model_id"},
            )
        if len(cleaned) > 200:
            raise InvalidRequestError(
                "An embedding model id is limited to 200 characters.",
                details={"field": "model_id"},
            )

        from codeatlas.semantic.providers import LocalEmbeddingProvider

        started = time.monotonic()
        try:
            provider = LocalEmbeddingProvider(model_id=cleaned)
        except Exception as error:  # noqa: BLE001 - reduced to a code below
            return EmbeddingModelValidation(
                model_id=cleaned,
                ok=False,
                dimensions=None,
                detail_code=_failure_code(error),
                latency_ms=int((time.monotonic() - started) * 1000),
            )
        return EmbeddingModelValidation(
            model_id=cleaned,
            ok=True,
            dimensions=provider.dimensions,
            detail_code=None,
            latency_ms=int((time.monotonic() - started) * 1000),
        )
```

`_failure_code` already exists at the bottom of the module and reduces an exception to a code so a provider message cannot leak. Reuse it; do not return `str(error)`.

- [ ] **Step 4: Add the route**

In `src/codeatlas/api/routers/settings.py`, beside the Ollama pull models:

```python
class ValidateEmbeddingModelBody(StrictModel):
    model_id: str = Field(min_length=1, max_length=200)


class ValidateEmbeddingModelResponse(StrictModel):
    provider: Literal["local"] = "local"
    model_id: str
    ok: bool
    # Measured by loading the model. Null when it could not be loaded.
    dimensions: int | None
    detail_code: str | None
    latency_ms: int
```

and the route beside `pull_ollama_model`:

```python
@router.post("/v1/models/embedding/validate")
def validate_embedding_model(
    services: Services, body: ValidateEmbeddingModelBody
) -> ValidateEmbeddingModelResponse:
    """Load a candidate local embedding model and report its vector width.

    Separate from saving because the first load downloads the model, which is
    large and slow. The request carries only a model name, never repository
    content.
    """
    result = services.settings.validate_embedding_model(body.model_id)
    return ValidateEmbeddingModelResponse(
        model_id=result.model_id,
        ok=result.ok,
        dimensions=result.dimensions,
        detail_code=result.detail_code,
        latency_ms=result.latency_ms,
    )
```

- [ ] **Step 5: Add the contract field to settings responses**

In the same file, add to `SettingsResponse`:

```python
    embedding_model: str | None
```

to `UpdateSettingsBody`:

```python
    embedding_model: str | None = Field(default=None, min_length=1, max_length=200)
```

and in `update_settings`, pass both through:

```python
            embedding_model=body.embedding_model,
            clear_embedding_model=(
                "embedding_model" in sent and body.embedding_model is None
            ),
```

Then find `_settings_response` in this file and add `embedding_model=settings.embedding_model,` to it.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest tests/contract/test_settings_api.py -v`
Expected: PASS, the whole file.

- [ ] **Step 7: Regenerate the API types and the OpenAPI export**

Run: `powershell -ExecutionPolicy Bypass -File scripts/generate_web_types.ps1`
Expected: `apps/web/openapi.json` and `apps/web/src/lib/api-types.gen.ts` gain the new endpoint and fields. Do not edit either by hand.

- [ ] **Step 8: Commit**

```bash
git add src/codeatlas/application/settings.py src/codeatlas/api/routers/settings.py tests/contract/test_settings_api.py apps/web/openapi.json apps/web/src/lib/api-types.gen.ts
git commit -m "feat: add an embedding model validation endpoint"
```

---

### Task 5: CLI parity

**Files:**
- Modify: `src/codeatlas/cli/main.py:1332` (`settings_command`)
- Test: `tests/contract/test_settings_cli.py`

**Interfaces:**
- Consumes: `SettingsService.update(..., embedding_model=…)` (Task 3).
- Produces: `codeatlas settings <id> --embedding-model <model>`.

Section 4.5 requires CLI, REST, MCP, and web to reach the same application service. A setting reachable only from the browser would break that.

- [ ] **Step 1: Write the failing test**

Add to `tests/contract/test_settings_cli.py`, matching the file's existing runner helper:

```python
def test_the_cli_can_set_an_embedding_model(tmp_path) -> None:
    """CLI and REST must offer the same setting on the same terms."""
    result = run_cli(
        [
            "settings",
            "repo-1",
            "--provider",
            "local",
            "--embedding-model",
            "BAAI/bge-small-en-v1.5",
            "--json",
        ]
    )

    assert result.exit_code == 0
    assert json.loads(result.stdout)["embedding_model"] == "BAAI/bge-small-en-v1.5"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/contract/test_settings_cli.py -k embedding_model -v`
Expected: FAIL — `No such option: --embedding-model`.

- [ ] **Step 3: Add the option**

In `settings_command`, after `per_run_budget`:

```python
    embedding_model: Annotated[
        str | None,
        typer.Option(
            "--embedding-model",
            help="Local embedding model id, for example BAAI/bge-small-en-v1.5.",
        ),
    ] = None,
```

Include it in the `changing` condition:

```python
    changing = (
        kind is not None
        or monthly_budget is not None
        or per_run_budget is not None
        or embedding_model is not None
    )
```

pass `embedding_model=embedding_model,` to `services.settings.update(...)`, and add to the `payload` dict:

```python
        "embedding_model": result.embedding_model,
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/contract/test_settings_cli.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/codeatlas/cli/main.py tests/contract/test_settings_cli.py
git commit -m "feat: set the embedding model from the CLI"
```

---

### Task 6: Web data layer

**Files:**
- Modify: `apps/web/src/lib/queries.ts:116` (`RepositorySettings`), `:176` (`SettingsUpdate`), `:253` (beside `usePullOllamaModel`)
- Test: `apps/web/src/features/settings/SemanticSettings.test.tsx`

**Interfaces:**
- Consumes: `POST /v1/models/embedding/validate` (Task 4).
- Produces: `useValidateEmbeddingModel()` returning a mutation over `EmbeddingModelValidation`.

- [ ] **Step 1: Add the types**

In `apps/web/src/lib/queries.ts`, add `readonly embedding_model: string | null;` to `RepositorySettings`, and `readonly embedding_model?: string | null;` to `SettingsUpdate`.

Add the result type beside the other provider result interfaces:

```typescript
/** The measured result of loading a candidate local embedding model. */
export interface EmbeddingModelValidation {
  readonly provider: "local";
  readonly model_id: string;
  readonly ok: boolean;
  /** Measured by loading the model. Null when it could not be loaded. */
  readonly dimensions: number | null;
  readonly detail_code: string | null;
  readonly latency_ms: number;
}
```

- [ ] **Step 2: Add the hook**

Beside `usePullOllamaModel`:

```typescript
export function useValidateEmbeddingModel() {
  return useMutation({
    mutationFn: (modelId: string) =>
      api.post<EmbeddingModelValidation>("/v1/models/embedding/validate", {
        model_id: modelId,
      }),
  });
}
```

- [ ] **Step 3: Verify types compile**

Run: `pnpm --dir apps/web exec tsc --noEmit`
Expected: exit 0.

- [ ] **Step 4: Commit**

```bash
git add apps/web/src/lib/queries.ts
git commit -m "feat: add the embedding model validation hook"
```

---

### Task 7: The Settings panel

**Files:**
- Modify: `apps/web/src/features/settings/SemanticSettings.tsx` (state at `:50`, save at `:106`, aside at `:229`)
- Test: `apps/web/src/features/settings/SemanticSettings.test.tsx`

**Interfaces:**
- Consumes: `useValidateEmbeddingModel` (Task 6), `SettingsUpdate.embedding_model` (Task 6).

Follow `documentation/design.md`: existing tokens only, no new component library, status carried by text as well as colour, and no skeleton for data that is not pending.

- [ ] **Step 1: Write the failing tests**

Add to `apps/web/src/features/settings/SemanticSettings.test.tsx`, matching the file's existing render helper and MSW-or-mock setup:

```typescript
it("shows the embedding model field only for the local provider", async () => {
  renderSettings({ embedding_provider: "local" });

  expect(
    await screen.findByLabelText(/embedding model/i),
  ).toBeInTheDocument();
});

it("hides the embedding model field for the openai provider", async () => {
  renderSettings({ embedding_provider: "openai" });

  await screen.findByRole("heading", { name: /semantic search/i });
  expect(screen.queryByLabelText(/embedding model/i)).not.toBeInTheDocument();
});

it("blocks saving a typed model until it has been checked", async () => {
  const user = userEvent.setup();
  renderSettings({ embedding_provider: "local" });

  await user.type(
    await screen.findByLabelText(/embedding model/i),
    "BAAI/bge-small-en-v1.5",
  );

  expect(screen.getByRole("button", { name: /^save$/i })).toBeDisabled();
});

it("reports the measured dimensions after a successful check", async () => {
  const user = userEvent.setup();
  renderSettings({ embedding_provider: "local" });

  await user.type(
    await screen.findByLabelText(/embedding model/i),
    "BAAI/bge-small-en-v1.5",
  );
  await user.click(screen.getByRole("button", { name: /check model/i }));

  expect(await screen.findByRole("status")).toHaveTextContent(/384 dimensions/i);
  expect(screen.getByRole("button", { name: /^save$/i })).toBeEnabled();
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pnpm --dir apps/web exec vitest run SemanticSettings`
Expected: FAIL — no element with an "embedding model" label.

- [ ] **Step 3: Add the state**

In `SemanticSettings`, beside the existing `useState` calls:

```typescript
  const [embeddingModel, setEmbeddingModel] = useState<string>("");
  // The model id proven to load, so a user cannot type past a failed check.
  // Reset whenever the field changes, because a checked id and an edited one
  // are not the same id.
  const [validatedModel, setValidatedModel] = useState<string | null>(null);
  const validateModel = useValidateEmbeddingModel();
```

Seed it in the existing `useEffect` over `settings.data`:

```typescript
      setEmbeddingModel(settings.data.embedding_model ?? "");
      setValidatedModel(settings.data.embedding_model ?? null);
```

Add the gate above the returned JSX:

```typescript
  const trimmedEmbeddingModel = embeddingModel.trim();
  // A blank field means "use the default", which needs no check.
  const embeddingModelReady =
    provider !== "local" ||
    trimmedEmbeddingModel === "" ||
    trimmedEmbeddingModel === validatedModel;
```

- [ ] **Step 4: Send the field on save**

In `save`, add to the `update.mutate({...})` object:

```typescript
      embedding_model:
        provider === "local" && trimmedEmbeddingModel !== ""
          ? trimmedEmbeddingModel
          : null,
```

and disable the submit button when the gate is closed — change its `disabled` to:

```typescript
              disabled={update.isPending || !embeddingModelReady}
```

- [ ] **Step 5: Add the panel**

In the `aside`, above the `answerProvider !== "none"` block:

```tsx
          {provider === "local" ? (
            <section className="rounded-[var(--radius-md)] border border-border bg-surface p-[var(--space-4)] shadow-sm">
              <label
                htmlFor="embedding-model"
                className="block text-sm font-medium"
              >
                Embedding model
              </label>
              <input
                id="embedding-model"
                type="text"
                value={embeddingModel}
                placeholder={chosen?.model_id ?? ""}
                onChange={(event) => {
                  setEmbeddingModel(event.target.value);
                  setValidatedModel(null);
                  validateModel.reset();
                }}
                aria-describedby="embedding-model-help"
                className="mt-[var(--space-2)] w-full rounded-[var(--radius-md)] border border-border bg-surface px-[var(--space-3)] py-[var(--space-2)] text-sm"
              />
              <p
                id="embedding-model-help"
                className="mt-[var(--space-2)] text-xs leading-5 text-text-muted"
              >
                Any sentence-transformers model, for example{" "}
                <code>BAAI/bge-small-en-v1.5</code>. Leave blank to use{" "}
                {chosen?.model_id ?? "the default"}. Checking a new model
                downloads it, which can take several minutes.
              </p>
              <button
                type="button"
                onClick={() => {
                  validateModel.mutate(trimmedEmbeddingModel, {
                    onSuccess: (result) => {
                      if (result.ok) setValidatedModel(result.model_id);
                    },
                  });
                }}
                disabled={
                  validateModel.isPending || trimmedEmbeddingModel === ""
                }
                className="mt-[var(--space-3)] w-full rounded-[var(--radius-md)] border border-border px-[var(--space-3)] py-[var(--space-2)] text-sm font-medium disabled:opacity-50"
              >
                {validateModel.isPending ? "Checking..." : "Check model"}
              </button>
              {validateModel.data ? (
                <p
                  role="status"
                  className={`mt-[var(--space-2)] text-sm ${
                    validateModel.data.ok ? "text-fresh" : "text-danger"
                  }`}
                >
                  {validateModel.data.ok
                    ? `${validateModel.data.model_id} loaded, ${validateModel.data.dimensions} dimensions.`
                    : `Could not load ${validateModel.data.model_id}: ${
                        validateModel.data.detail_code ?? "unknown"
                      }.`}
                </p>
              ) : null}
              {trimmedEmbeddingModel !== "" && !embeddingModelReady ? (
                <p className="mt-[var(--space-2)] text-xs leading-5 text-text-muted">
                  Check the model before saving. The vector index is labelled
                  with its width, so CodeAtlas measures it rather than guessing.
                </p>
              ) : null}
            </section>
          ) : null}
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `pnpm --dir apps/web exec vitest run SemanticSettings`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add apps/web/src/features/settings/SemanticSettings.tsx apps/web/src/features/settings/SemanticSettings.test.tsx
git commit -m "feat: choose a local embedding model in Settings"
```

---

### Task 8: Re-embed action

**Files:**
- Modify: `apps/web/src/features/settings/SemanticSettings.tsx`
- Modify: `apps/web/src/lib/queries.ts`
- Test: `apps/web/src/features/settings/SemanticSettings.test.tsx`

**Interfaces:**
- Consumes: `POST /v1/models/embedding-migrations` (exists, `api/routers/settings.py:257`).
- Produces: `useStartEmbeddingMigration(repositoryId)`.

The endpoints already exist from P7-09. This task only surfaces them; do not modify the migration service.

- [ ] **Step 1: Add the hook**

In `queries.ts`, beside `useValidateEmbeddingModel`:

```typescript
export interface EmbeddingMigration {
  readonly migration_id: string;
  readonly repository_id: string;
  readonly status: string;
  readonly source_namespace_id: string;
  readonly target_namespace_id: string;
}

export function useStartEmbeddingMigration(repositoryId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () =>
      api.post<EmbeddingMigration>("/v1/models/embedding-migrations", {
        repository_id: repositoryId,
      }),
    onSuccess: () => {
      void client.invalidateQueries({
        queryKey: ["semantic-status", repositoryId],
      });
    },
  });
}
```

Confirm the response field names against `EmbeddingMigrationResponse` in `src/codeatlas/api/routers/settings.py:131` before writing this, and match them exactly.

- [ ] **Step 2: Write the failing test**

```typescript
it("offers re-embedding when the saved model differs from the active namespace", async () => {
  renderSettings({
    embedding_provider: "local",
    embedding_model: "BAAI/bge-small-en-v1.5",
  });

  expect(
    await screen.findByRole("button", { name: /re-embed/i }),
  ).toBeInTheDocument();
});
```

The active namespace's model is already exposed: `SemanticStatusResponse.model_id` (`src/codeatlas/api/routers/repositories.py:126`). No backend change is needed. Drive the condition from `status.data?.model_id`, and add the field to the web `SemanticStatus` interface in `queries.ts` if it is not there yet.

- [ ] **Step 3: Run the test to verify it fails**

Run: `pnpm --dir apps/web exec vitest run SemanticSettings`
Expected: FAIL — no re-embed button.

- [ ] **Step 4: Add the action**

Inside the embedding-model panel, below the check button, rendered only when the saved model differs from the active namespace's model:

```tsx
              <div className="mt-[var(--space-3)] border-t border-border pt-[var(--space-3)]">
                <button
                  type="button"
                  onClick={() => startMigration.mutate()}
                  disabled={startMigration.isPending}
                  className="w-full rounded-[var(--radius-md)] border border-border px-[var(--space-3)] py-[var(--space-2)] text-sm font-medium disabled:opacity-50"
                >
                  {startMigration.isPending
                    ? "Re-embedding..."
                    : "Re-embed with the new model"}
                </button>
                <p className="mt-[var(--space-2)] text-xs leading-5 text-text-muted">
                  Existing vectors keep serving search until the new ones are
                  complete. Vectors from two models cannot share one similarity
                  space, so the new model starts an empty namespace.
                </p>
              </div>
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `pnpm --dir apps/web exec vitest run SemanticSettings`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add apps/web/src/lib/queries.ts apps/web/src/features/settings/SemanticSettings.tsx apps/web/src/features/settings/SemanticSettings.test.tsx
git commit -m "feat: offer re-embedding after an embedding model change"
```

---

### Task 9: ADR, documentation, and the full gate

**Files:**
- Create: `docs/adr/0014-per-repository-embedding-model.md`
- Modify: `docs/adr/README.md`, `docs/operations/semantic-search.md`, `.env.example`, `README.md`, `documentation/architecture.md`, `documentation/memory.md`, `docs/plans/PLAN.md`

- [ ] **Step 1: Write ADR-0014**

Follow `docs/adr/0000-template.md` exactly. Content: extend ADR-0011's reasoning from a machine-wide `.env` value to a per-repository stored one. State the decision (nullable column, policy → env → default precedence, validation measures the width), the consequences (a model change needs a re-embed; the namespace key is unchanged), and the alternatives rejected (curated dropdown; OpenAI in the same field; server-enforced validation). Do not rewrite ADR-0011 — it stays the record of what was decided at the time.

- [ ] **Step 2: Correct the stale migration range**

`documentation/architecture.md:135` says migrations `0001`–`0011`. The tree has `0014` after this work. Fix the range and add `embedding_model` to the Repository-truth section's description of provider policy.

- [ ] **Step 3: Update the operations doc**

In `docs/operations/semantic-search.md`, document choosing a model in Settings, the check step and why the width is measured, and that a model change needs a re-embed with cutover and rollback.

- [ ] **Step 4: Note the precedence in .env.example**

Beside `CODEATLAS_LOCAL_EMBEDDING_MODEL`, record that a per-repository setting now outranks it.

- [ ] **Step 5: Run the full gate**

Run: `powershell -ExecutionPolicy Bypass -File scripts/check_phase7.ps1 -SkipSync`
Expected: exit 0. Record the actual command, exit code, and counts. If a step fails, fix the cause — do not skip the step or weaken a test.

- [ ] **Step 6: Append the handoff entry**

Append — never rewrite — an entry to `docs/plans/PLAN.md` following the Handoff Schema: UTC timestamp, agent, transition, outcome, files, contracts (`contract_version` stays `1.1`; migration `0014`; additive endpoint), verification with real numbers, limitations, next. Update `documentation/memory.md` in the same commit.

- [ ] **Step 7: Commit**

```bash
git add docs/ documentation/ .env.example README.md
git commit -m "docs: record ADR-0014 and per-repository embedding models"
```

---

## Definition of Done

- A user selects the local provider, types any sentence-transformers model id, checks it, sees measured dimensions, and saves.
- The choice is per repository and survives a restart.
- A repository that never chose a model behaves exactly as before.
- The migration backfill uses the repository's model, not the `.env` one.
- CLI and REST accept the same setting on the same terms.
- `check_phase7.ps1 -SkipSync` exits 0, with the output recorded.

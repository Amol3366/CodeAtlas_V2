# `.env` configuration for provider credentials and model selection

Date: 2026-08-01
Status: approved by the user 2026-08-01
Policy authority: `CLAUDE.md`
Related: ADR-0009 (measured semantic uplift), ADR-0010 (repository-scoped
namespaces), `docs/security/threat-model.md`

## Problem

CodeAtlas can already embed with OpenAI or with a local sentence-transformers
model, but neither is configurable in practice:

- **The credential must be exported into the shell.** `OpenAIEmbeddingProvider`
  reads `OPENAI_API_KEY` from `os.environ`, and `describe_available_providers()`
  gates the OpenAI option on the same variable. On a workstation that means
  setting a machine-wide variable, or re-exporting it in every terminal, before
  the settings page will even *offer* OpenAI.
- **The models are pinned constants.** `LOCAL_MODEL_ID` and `OPENAI_MODEL_ID`
  cannot be changed without editing source, so "use a different open-source
  embedding model" is not a thing a user can do.

Both constructors already accept a `model_id` override and nothing passes one.
The plumbing exists; the configuration source does not.

## Scope

**In:** a `.env` file supplying the OpenAI credential and overriding both
providers' model identity, loaded from a fixed location, with `.env.example`
and the `.gitignore` fix.

**Out, as recorded decisions rather than omissions:**

- **OpenAI-compatible base URLs** (Ollama, LM Studio, vLLM as embedding
  backends). It is the cheapest path to open-source models and worth doing
  later, but it makes `transmits_off_machine` — currently a per-provider-kind
  constant — depend on a URL, and a privacy label that can be wrong in the
  reassuring direction is worse than no feature.
- **LLM answer generation.** Only `NoAnswerProvider` exists. Phase 7 recorded
  generation as `declined`, and the threat model lists concrete answer providers
  as "not shipped", pending a governed answer-provider policy and measured
  uplift. Shipping it needs its own ADR, evaluation, and approval.

Open-source model support is delivered here through the **local** provider with
a configurable model, which transmits nothing by construction.

## The line this design will not cross

`build_embedding_provider`'s docstring states it outright:

> There is deliberately no environment variable or global override that could
> enable a provider for a repository whose stored policy says `none` —
> Section 4.4 draws the boundary per repository, and a second way to switch it
> on is a second way to get it wrong.

**`.env` supplies credentials and model identity. It never supplies consent.**
Whether a repository may transmit stays in `repository_provider_policy` in
SQLite, per repository, set through the settings surface. No variable added by
this design can turn a `none` repository into a transmitting one, and a test
asserts it.

## Decisions

| # | Decision | Rejected alternative |
| --- | --- | --- |
| 1 | Credential keeps its universal name `OPENAI_API_KEY`; CodeAtlas settings are namespaced `CODEATLAS_*`, matching `CODEATLAS_DB_PATH` | `CODEATLAS_OPENAI_API_KEY` with a fallback — two names for one secret, and a precedence rule to explain |
| 2 | Precedence is **real environment > `.env` > pinned default**, implemented with `os.environ.setdefault` | `.env` winning — a stale file would silently outrank a deliberate export, and CI could not override |
| 3 | `.env` is read from `$CODEATLAS_ENV_FILE`, else **the CodeAtlas root** — the project folder in a source checkout, the install folder beside `codeatlas.exe` when packaged. Resolved from the package's own location, **never from the current directory** | Current-directory search — running CodeAtlas inside an indexed repository would let that repository's `.env` become application configuration, inverting §4.4. A fixed root is not the current directory and does not have this property |
| 7 | `.env`, `.env.*`, and `*.env` join `DEFAULT_IGNORE_PATTERNS` | Leaving them scannable. Blueprint §8.11 names "exclude `.env` by default" as a required control, and this design puts a credential file at a repository root — an unignored one would surface in file search results |
| 4 | A custom OpenAI model **requires** an explicit dimensions setting | Assuming 1536, which silently corrupts the similarity space; or probing the API, which bills a call per provider construction |
| 5 | Hand-rolled ~40-line parser, no new runtime dependency | `python-dotenv` — the repo hand-rolls a YAML line scanner and uses stdlib `tomllib` only, precisely to keep untrusted-input parsers small and auditable |
| 6 | A new ADR-0011 amends ADR-0009 decision 4 | Editing ADR-0009, which the ADR process forbids |

## Design

### The variables

```ini
# The credential. Universal name, because every other tool uses it.
OPENAI_API_KEY=sk-...

# Optional. Defaults to the pinned text-embedding-3-small.
CODEATLAS_OPENAI_EMBEDDING_MODEL=text-embedding-3-small

# Required *only* when the model above is not the pinned default.
CODEATLAS_OPENAI_EMBEDDING_DIMENSIONS=1536

# Optional. Defaults to the pinned sentence-transformers/all-MiniLM-L6-v2.
# Any sentence-transformers-compatible model; transmits nothing.
CODEATLAS_LOCAL_EMBEDDING_MODEL=BAAI/bge-small-en-v1.5
```

### Why dimensions are separate and required

`OpenAIEmbeddingProvider.dimensions` is the constant `1536`, and
`embedding_namespace_id` derives the vector namespace from
`(model_id, dimensions, normalization_version)`. Pointing the model at
`text-embedding-3-large` (3072-wide) while the class still reports 1536 would
write 3072-float vectors into a namespace labelled 1536 — a corrupted
similarity space that announces nothing and is discovered as bad search
results months later.

So when `CODEATLAS_OPENAI_EMBEDDING_MODEL` differs from the pinned default and
`CODEATLAS_OPENAI_EMBEDDING_DIMENSIONS` is absent, provider construction raises
`ProviderUnavailableError` naming the missing variable. Refuse rather than
corrupt.

The local provider needs no equivalent: `_embedding_dimension` already asks the
loaded model its width. Asking OpenAI the same question costs a billable call
per construction, which is why the asymmetry exists rather than being an
oversight.

### Loading

New package `src/codeatlas/settings/` — the one CLAUDE.md §7 specifies and the
tree never grew — containing `env_file.py`:

```python
def load_env_file(path: Path | None = None) -> LoadedEnv:
    """Apply `.env` values that the real environment has not already set."""
```

Behavior:

1. Resolve the path: explicit argument, else `$CODEATLAS_ENV_FILE`, else
   `<codeatlas-root>/.env`.

   **The CodeAtlas root is resolved from the package's own location, not from
   the current directory.** In a source checkout that is the project folder
   containing `pyproject.toml` — walking up from `codeatlas.__file__` through
   `src/codeatlas` — so a developer's `.env` sits at the repository root where
   they expect it. In a PyInstaller build `sys.frozen` is set and the root is
   the folder containing the executable.

   The distinction from a current-directory search is the whole point and is
   easy to lose: this path is **fixed for a given installation**. Running
   `codeatlas` from inside some other repository reads CodeAtlas's `.env`, not
   that repository's, so no indexed repository can supply configuration. A test
   asserts exactly this by planting a `.env` in a repository root, running from
   there, and observing that nothing was applied.

   If the install folder is not writable, `CODEATLAS_ENV_FILE` is the answer;
   it is checked first for that reason.

   The credential does not enter backups: `codeatlas backup` copies the
   database file, which lives under the data directory, not the CodeAtlas root.
2. A missing file is normal and returns an empty result. It is not an error and
   emits no warning.
3. Parse `KEY=VALUE` lines. Support `#` comments, blank lines, `export ` prefix,
   surrounding single or double quotes, and trailing comments outside quotes.
   **Skip malformed lines rather than raising** — a broken config line must not
   stop a deterministic tool from starting.
4. Apply with `os.environ.setdefault`, which produces the required precedence
   without a branch.
5. Return which keys were applied — **names only, never values** — so a caller
   can report "3 settings loaded" without putting a credential anywhere.

`LoadedEnv` carries `path: Path | None` and `applied: tuple[str, ...]`.

### Where it is called

Once per process, at each entry point, before anything reads `os.environ`:

- `codeatlas.cli.main.main()`
- `codeatlas.api.app.create_app()`
- `codeatlas.mcp.server`'s entry point

Idempotent, so a process that is both CLI and API loses nothing by calling
twice. It must precede `describe_available_providers()`, which is what makes
the OpenAI option appear in settings.

### Threading the model IDs through

`build_embedding_provider` and `ProviderFactory.build` read the configured
values and pass them to the constructors that already accept them:

- local → `_cached_local_provider(model_id=configured)`; the `lru_cache` key
  already includes the model ID, so two models cannot collide in one process.
- OpenAI → `OpenAIEmbeddingProvider(model_id=configured, dimensions=resolved)`.
  `dimensions` becomes a constructor parameter; it is currently a class
  attribute only.

Reading happens through small helpers in `settings/env_file.py`
(`openai_embedding_model()`, `openai_embedding_dimensions()`,
`local_embedding_model()`) so no provider code calls `os.environ` directly and
the defaults live in one place.

### `.env.example`

Committed at the repository root, and the file a user copies and edits. It
lists **every** variable this design introduces — including the optional ones —
each with a comment saying what it does, whether it is required, and what the
pinned default is. Values are placeholders (`sk-your-key-here`), never real.

It is documentation that happens to be executable: someone who reads only this
file should be able to configure both providers without opening the operations
guide.

### Keeping `.env` out of the scan

`.env`, `.env.*`, and `*.env` join `DEFAULT_IGNORE_PATTERNS` in
`repositories/ignore_rules.py`.

Scope of the change, stated precisely so it is not oversold: a `.env` file
classifies as `unknown` with no parser, so its **contents are already never
parsed, chunked, indexed into FTS, or embedded**. What an unignored `.env`
does today is appear in file-path search results. Ignoring it is
blueprint §8.11 conformance and good hygiene for a design that asks users to
put a credential at a repository root — it is not the closing of a live leak,
and the ADR says so.

Users who deliberately want their `.env` indexed can override this through
`.codeatlasignore`, which already takes precedence over built-in patterns.

### What the settings surface reports

`SettingsService.models()` reports the **configured** model ID rather than the
constant. When a custom OpenAI model is configured without dimensions it
reports `available: false` with `requires` naming the missing variable — the
same mechanism that already explains a missing extra. When a custom local model
is configured, `dimensions` is reported as `null`, because the width is not
known until the model loads and loading it to render a form is what
`describe_available_providers` exists to avoid.

## Security

`.gitignore` gains `.env` **in the first commit, before any loader exists**, so
there is no window in which a real credential is one `git add -A` from being
committed.

| Control | How |
| --- | --- |
| The credential never reaches a response | Tests assert it is absent from `GET /v1/settings`, `GET /v1/models`, `/v1/repositories/{id}/diagnostics`, and the error envelope |
| The credential is never logged | The loader returns key *names*; no value is returned, stored, or formatted anywhere |
| The credential is not retained in memory | Unchanged — `OpenAIEmbeddingProvider` still hands it to the client and lets it go out of scope |
| Repository content cannot become configuration | The current directory is never searched — the root is resolved from the package's own location. A test plants a `.env` in a repository root, runs from that directory, and asserts nothing was applied |
| A credential file is not surfaced by search | `.env`, `.env.*`, and `*.env` are ignored by default; a test scans a fixture containing one and asserts it is absent from the manifest with a skip reason |
| A malformed file cannot deny service | Malformed lines are skipped; a test feeds binary, a 1 MB line, and unterminated quotes |
| Consent still comes only from SQLite | A test sets every variable, leaves the repository policy `none`, and asserts the provider built is `NoEmbeddingProvider` |

## Testing

- **Unit** (`tests/unit/test_env_file.py`): parsing — comments, quotes, `export`,
  blank lines, `=` inside values, malformed lines, CRLF, BOM, missing file;
  precedence, asserting a pre-set real variable is not overwritten.
- **Unit** (`tests/unit/test_embedding_providers.py`, extended): configured
  model IDs reach the constructors; a custom OpenAI model without dimensions
  raises `ProviderUnavailableError` naming the variable.
- **Integration** (`tests/integration/test_settings_service.py`, extended):
  `models()` reports configured IDs and the `available: false` case.
- **Unit** (`tests/unit/test_ignore_rules.py`, extended): `.env`, `.env.local`,
  and `app.env` are ignored by default, and `.codeatlasignore` can still
  un-ignore them.
- **Security** (`tests/security/test_env_configuration.py`, new): the seven
  controls in the table above.
- **Contract**: `GET /v1/models` shape is unchanged — `dimensions` was already
  `int | None`.

No migration. No REST contract change. No change to any snapshot, evidence, or
persistence contract.

## Records

| File | Change |
| --- | --- |
| `docs/adr/0011-configurable-embedding-models.md` | New. Amends ADR-0009 decision 4; records why configurable models are safe (namespace identity derives from model identity, so a change creates a new namespace and shadow migration moves between them) |
| `docs/adr/README.md` | Index row |
| `.env.example` | New, at the repository root, committed, with no real values |
| `.gitignore` | `.env`, `.env.*` (keeping `!.env.example`) |
| `src/codeatlas/repositories/ignore_rules.py` | `.env` patterns in `DEFAULT_IGNORE_PATTERNS` |
| `docs/operations/semantic-search.md` | Configuring a provider and a model |
| `docs/security/threat-model.md` | Phase 7 table gains the `.env` controls |
| `docs/plans/PLAN.md` | Handoff entry |

## Verification

```powershell
uv run pytest
uv run ruff check .
uv run mypy src
powershell -ExecutionPolicy Bypass -File scripts/check_phase7.ps1 -SkipSync
```

Exit codes recorded in the PLAN handoff. The semantic extras are **not**
installed, so the OpenAI and local providers are exercised through their
existing fake-transport and import-failure paths, exactly as they are today.

## Acceptance criteria

1. `OPENAI_API_KEY` placed in `.env` is visible to
   `describe_available_providers()` with no shell export — so the credential
   half of the OpenAI availability check passes on its own. With the extra
   absent, as it is here, the option still reports unavailable naming the
   extra; that half is unchanged and is what the existing tests already cover.
   The two halves are asserted separately, because the extra cannot be
   installed to assert them together.
2. A variable exported in the real environment is not overwritten by `.env`.
3. `CODEATLAS_LOCAL_EMBEDDING_MODEL` changes which sentence-transformers model
   the local provider loads.
4. A custom OpenAI model without `CODEATLAS_OPENAI_EMBEDDING_DIMENSIONS` is
   refused with an error naming the missing variable — never embedded.
5. `.env` at the CodeAtlas root is read in a source checkout and in a packaged
   build. A `.env` in the current working directory — when that is some other
   repository — is **not** read.
5a. `.env`, `.env.local`, and `app.env` are excluded from repository scans by
   default, and `.codeatlasignore` can still override that.
6. No variable in `.env` can cause a repository whose policy is `none` to
   transmit.
7. The credential appears in no API response, diagnostic, or log.
8. `.env` is gitignored; `.env.example` is committed and contains no real value.
9. `check_phase7.ps1 -SkipSync` exits 0.

# CodeAtlas Local MVP Threat Model

Status: accepted Phase 0 baseline  
Last reviewed: 2026-07-25  
Applies to: the single-user, local Windows MVP

## Security Objective

CodeAtlas reads hostile repositories without executing them, keeps source and
derived content local by default, resolves all paths inside an explicitly
approved root, and emits only snapshot-bound verified evidence. Optional
providers remain disabled until a repository owner explicitly opts in.

## Assets

- repository source, filenames, history, metadata, and derived indexes;
- local filesystem paths, Git state, settings, diagnostics, and secrets;
- snapshot membership, evidence, findings, and conversation history;
- provider credentials, budgets, redaction decisions, and audit metadata;
- local service integrity and availability.

## Trust Boundaries

1. **Repository boundary:** every byte, path, filename, document, configuration
   value, comment, and Git field is untrusted data.
2. **Filesystem boundary:** only canonical paths below the approved repository
   root may be read. Symlinks and Windows junctions require resolved-target
   containment checks.
3. **Process boundary:** Git is invoked through an argument-array adapter.
   Repository code, imports, hooks, builds, tests, scripts, binaries, and
   generated commands are never executed during indexing.
4. **Local API boundary:** the API binds to loopback by default. Network
   exposure requires a revised threat model and explicit approval.
5. **Provider boundary:** no repository content crosses it unless the selected
   repository has explicit opt-in, secret/redaction checks pass, and budgets and
   timeouts are active.
6. **Presentation boundary:** Markdown, excerpts, model output, and repository
   links are sanitized and cannot inject HTML, scripts, styles, handlers, or
   application instructions.

## Threats and Required Controls

| Threat | Required control | Failure behavior |
| --- | --- | --- |
| `..`, absolute, UNC, drive, reserved-name, case-folding, or invalid-Unicode path escape | Normalize and resolve; compare the canonical target to the canonical approved root; validate again before evidence leaves the application layer | Reject the entity and emit a bounded diagnostic |
| Symlink or junction escape | Inspect and resolve each traversed target; never follow a target outside the root | Skip/reject and record a security warning |
| Malformed, deeply nested, oversized, binary, or adversarial input | Classification, size/depth limits, parser timeout, bounded diagnostics | Continue safely when possible; never activate an invalid snapshot |
| Repository command or package-script execution | Indexing uses data-only readers; Git adapter uses non-shell argument arrays; hooks disabled where applicable | Reject the operation; do not retry deterministic policy failures |
| SQL/FTS injection | Parameterized SQL and a validated FTS query builder; no raw dynamic SQL | Return a stable invalid-input error |
| Prompt injection in repository text | Treat retrieved content as quoted data; deterministic facts remain authoritative; providers receive only approved, bounded evidence | Reject unsupported claims or explicitly abstain |
| Secret leakage | Provider opt-in, secret scanning/redaction, bounded excerpts, no raw source/prompts/answers in logs or exports by default | Block provider call and return a redacted warning |
| Cross-snapshot or invented evidence | Repository/snapshot membership checks, canonical paths, line validation, evidence-ID resolution, final claim validation | Reject the claim or result |
| Browser Markdown/HTML injection | Sanitized Markdown, safe link schemes, no raw HTML or event handlers | Render inert text or remove the unsafe element |
| Arbitrary editor/file opening | Allowlisted local command/protocol with canonical repository-relative target | Refuse unsafe target |
| Local API exposure, CORS, or CSRF abuse | Loopback binding and restrictive CORS; network binding requires authentication and approval | Refuse unsupported configuration |
| Secret or content logging | Opaque IDs and aggregate telemetry; absolute paths, prompts, excerpts, source, answers, and secrets excluded by default | Redact and emit a diagnostic |
| Denial of service | Query length, result, graph, evidence, parser, Git, storage, provider, and end-to-end limits with cancellation | Return bounded timeout/cancel status |

## Phase 1 Enforcement Status

As of 2026-07-25 the following controls are implemented and covered by tests in
`tests/security/`. Everything not listed remains a design commitment only.

| Control | Status | Where it is enforced |
| --- | --- | --- |
| Path traversal, absolute, backslash, UNC, reserved-name, trailing dot/space rejection | enforced | `domain/paths.py`, `test_path_safety.py`, `test_windows_paths.py` |
| Symlink and Windows junction escape | enforced | `repositories/scanner.py` excludes with `SECURITY_LINK_ESCAPE`; a junction inside the root is still followed |
| Size, depth, path-length, and file-count limits | enforced | `domain/repository.py` `ScanLimits`, `test_scanner.py` |
| No execution of repository code | enforced | scanner and parser are data-only readers; asserted by tests that plant a side effect and by a source scan for execution primitives |
| Non-shell Git invocation | enforced | `repositories/git_state.py` uses argument arrays with `cwd`; asserted by test |
| Git scope confusion | enforced | a root that is not the Git top level yields `GIT_ROOT_MISMATCH` and no Git facts |
| SQL injection | enforced | every statement in `storage/sqlite/stores.py` is parameterized |
| Cross-snapshot or invented evidence | enforced | snapshot-scoped queries, pre-activation validation, content-hash re-verification at query time, contract-level membership checks |
| Stale evidence | enforced | drifted files are detected by hash and their evidence is withheld with `EVIDENCE_STALE_FILE_CONTENT` |
| Loopback-only API, no CORS | enforced | `apps/api/main.py`, asserted by test |
| No secrets, paths, or traces in errors | enforced | `api/errors.py`; asserted by a test that raises a secret-bearing exception |
| FTS5 query injection | enforced | user text never becomes FTS syntax; `retrieval/fts_query.py` reduces it to quoted literal terms, and `tests/security/test_fts_injection.py` runs twelve hostile queries against a real populated index, asserting each either raises `SearchQueryError` or returns bounded results |
| Untrusted document content | enforced | Markdown, JSON, YAML, and TOML are read for structure only; text that reads like an instruction is stored as text. `json` and `tomllib` are the only deserializers, YAML is a line scanner with no library, and a source scan asserts the absence of `exec`, `eval`, `importlib`, `runpy`, `subprocess`, `yaml.load`, and `pickle` |
| Path references named in prose | enforced | a path mentioned in a document is recorded only if it passes `validate_relative_path`; a test proves `../../etc/passwd` and `C:/Windows/system32` are not recorded |
| Searchable orphans after deletion | enforced | FTS5 virtual tables have no foreign keys, so pruning and abandoned-attempt cleanup clear the projections explicitly rather than relying on a cascade |
| Prompt injection, secret scanning, provider boundary | not applicable yet | no provider or model exists |
| Markdown/HTML injection, editor opening | not applicable yet | no UI exists |
| Content logging | not applicable yet | no logging framework exists and no logs are written |

## Phase 4 Enforcement Additions

As of 2026-07-27 the change-assurance surface adds these controls, covered by
`tests/security/test_git_diff_injection.py` and the unit/integration suites
named below.

| Control | Status | Where it is enforced |
| --- | --- | --- |
| Git ref injection (`--upload-pack=...`, `-c ...`, `;`, `..` outside a range, NUL) | enforced | `repositories/git_diff.py` `_validate_ref` grammar before any ref becomes an argument; hostile refs raise `GIT_REF_UNRESOLVABLE`, asserted by `test_git_diff_injection.py` |
| Paths from Git output escaping the root | enforced | every `ls-tree`, `name-status`, and archive entry name passes `validate_relative_path` before use; failures are dropped, never followed |
| Oversized blobs | enforced | `read_blob` and `archive` raise `ScanLimitExceededError` at the configured byte limit; the archive path refuses the same trees the per-blob path refuses |
| Archive/per-blob equivalence | enforced | `git archive` runs with text conversion disabled and is asserted byte-identical to raw blob reads, so one tree cannot hash two different ways |
| Hostile `.codeatlas/rules.toml` | enforced | stdlib `tomllib` only; schema-validated, bounded rule count, unknown fields refused with `ANALYSIS_RULES_INVALID`; rule text never becomes a command or a path outside the root |
| Repository text in reports | enforced | Markdown rendering escapes per construct (tables, code spans, control characters stripped); SARIF emits repository-relative URIs only; asserted by the renderer test suites |
| Injection-marker prose in changed documents | enforced | matched content is *labeled* (`UNTRUSTED_CONTENT_CHANGED` + `REPOSITORY_CONTENT_IS_DATA`), never obeyed; the marker list only labels, it never gates safety |
| Analysis audit integrity | enforced | stored analyses are decomposed rows with persisted rank; findings without citable evidence are dropped rather than emitted uncited |

## Phase 5 Enforcement Additions (browser surface)

As of 2026-07-28 the web application adds these controls, covered by the
component suites in `apps/web/src/**/*.test.tsx`.

| Control | Status | Where it is enforced |
| --- | --- | --- |
| Markdown/HTML injection | enforced | `components/Markdown.tsx` uses `rehype-sanitize` with an allowlist and **no `rehype-raw`**, so raw HTML never enters the tree; ten tests cover script tags, inline `onerror`, `<style>`, `<iframe>`, raw HTML, and a fenced block containing a script |
| Unsafe link protocols | enforced | only `http`/`https`/`mailto` survive sanitization; `javascript:` and `data:` are stripped, asserted by test |
| Reverse tabnabbing | enforced | every rendered link carries `rel="noopener noreferrer nofollow"` |
| Evidence excerpt injection | enforced | excerpts render inside `<pre><code>` as text and are never passed through the Markdown renderer, asserted by test |
| Unverified evidence display | enforced | a failed hash verification or missing row renders an explicit refusal with its error code; current file contents are never substituted under an old citation |
| Error detail leakage to the browser | enforced | the client renders only the Section 12.6 envelope's `code` and `message`; the error boundary logs nothing, because an exception can carry a path or repository content |
| Local API exposure | unchanged | the API still binds to loopback with no CORS middleware; the Vite dev proxy — not a relaxed server policy — is what lets the browser reach it in development |
| Browser storage of secrets | not applicable | the only stored value is the theme preference; no credential or repository content is written to `localStorage` |

## Phase 6 Enforcement Additions

Reviewed 2026-07-28 (P6-08). The controls below are asserted by
`tests/security/test_packaged_surface.py`, which drives the **real packaged
executable** rather than the source tree — the rest of `tests/security/` covers
parser limits, path canonicalization, and FTS injection in process, none of
which change when the code is frozen. A packaging defect lives precisely in the
gap between the two, so testing the source tree twice would not find one.

| Control | Status | Where it is enforced |
| --- | --- | --- |
| Loopback-only binding, packaged | enforced | the running executable is probed on this machine's LAN address and must refuse the connection. A constant proves what someone intended; a socket proves what happened |
| Binding beyond loopback | enforced | `serve --host 0.0.0.0` **refuses** and says why, in the packaged build as in source. A refusal cannot be lost by a flag the way a default can |
| CORS headers, packaged | enforced | no `access-control-*` header is returned. One origin is what lets the API register no CORS middleware; a header here would mean that reasoning had quietly stopped holding |
| Error envelope, packaged | enforced | a 404 from the binary carries the contract envelope, no traceback, no filesystem path, no bundle path |
| SPA fallback swallowing the API | enforced | an unknown `/v1` path returns the **JSON error envelope**, not the shell. P6-08 found it returning a bare 404 with an empty body — not HTML, so the fallback rule held, but a client reading `error.code` met a parse failure |
| Traversal through the static mount | enforced | four encodings of `..` are refused; the executable is never served |
| Developer material in the release | enforced | the bundle ships no `.env`, `.git`, database, lockfile, test fixture, `.spec.ts`, or stray `.sql` outside `migrations/` |
| Schema from a newer build | enforced | `apply_migrations` refuses a database recorded above this build's `SCHEMA_VERSION` with `SCHEMA_VERSION_UNSUPPORTED`, before anything is opened for writing. Reading a schema this build has never seen would open the tables, answer plausibly, and write into columns whose meaning had changed — corruption that announces itself only later. The guard sits in the migration path rather than in the upgrade command, so no call site bypasses it |
| Data loss during migration | enforced | any pending migration against a non-empty database is preceded by a verified checkpoint; a checkpoint that cannot be written stops the migration. Asserted against a database written by a real prior build, not a synthetic one |
| Install over a running process | enforced | `install_windows.ps1` refuses while `codeatlas.exe` is running from the install folder, rather than deleting it out from under a live process and leaving a half-replaced install |
| Unbounded local storage growth | enforced | indexing applies snapshot retention, so a watched repository reindexed all day no longer keeps every snapshot forever. Before P6-08 nothing called `prune`; the local database grew without limit for as long as CodeAtlas ran |

### Availability

| Control | Status | Where it is enforced |
| --- | --- | --- |
| Denial of service through the server's own output | enforced | `serve` runs with uvicorn's access log off. It wrote one line per request **on the event-loop thread**; a server launched with a pipe for stdout that nobody reads filled that pipe and blocked forever, taking every request with it. `tests/integration/test_serve_output_backpressure.py` drives 400 requests at a server whose output is never read |

This was recorded here on 2026-07-28 as an unfixed memory-fault crash. It was
diagnosed properly and fixed on 2026-07-29; the wrong diagnosis, and what made
it wrong, are kept in `docs/evaluation/phase-6-baseline-environment.md` rather
than deleted.

Turning the access log off also aligns the server with Section 17: this product
writes no logs by default, and an access log records a request path per request.

## Provider Opt-In Gate

Provider use is prohibited until all of the following are recorded for the
repository: provider identity and purpose, content classes permitted, explicit
user consent, secret/redaction policy, token and cost limits, timeouts,
cancellation, telemetry without content, deterministic fallback, and a
revocation path. Credentials never appear in GET responses, browser storage,
history exports, logs, or diagnostic bundles.

## Phase 7 Enforcement Status

| Control | Status | Evidence |
| --- | --- | --- |
| Provider default off | enforced | missing `repository_provider_policy` rows resolve to provider `none`; settings/API/CLI tests assert the default |
| Local provider boundary | enforced | `LocalSentenceTransformerProvider` has no network client and is reached only through explicit repository opt-in |
| OpenAI embedding boundary | enforced for embeddings | `ProviderFactory` wraps OpenAI with redaction, budgets, retries, timeouts, and usage telemetry; direct ungoverned construction is refused by tests |
| Secret redaction | enforced for transmitting embedding calls | outbound texts pass through `semantic.redaction.redact`; tests assert common secret shapes are replaced before the fake provider sees them |
| Provider telemetry without content | enforced | `provider_usage` stores provider, model, operation, counts, token estimate, latency, outcome, and time; schema tests assert no prompt/source/answer columns exist |
| Semantic snapshot authority | enforced | vector candidates are filtered against SQLite active snapshot membership; stale-vector tests assert physically retained vectors cannot answer |
| Shadow embedding migration | enforced | migration endpoints create a shadow namespace, backfill, dual-write, activate atomically, and retain rollback |
| Reranking | declined | `NoReranker` is the only implementation; `docs/evaluation/rerank-phase-7.{json,md}` records no uplift and no provider call |
| Generated explanations | declined | `NoAnswerProvider` is the only implementation; fake-provider tests reject unsupported generated claims and `docs/evaluation/explanation-phase-7.{json,md}` records no uplift |
| Concrete answer providers | not shipped | Ollama/OpenAI answer providers require a governed answer-provider policy and measured uplift before admission |

## Logging and Diagnostics

Default telemetry may contain opaque repository/snapshot/request IDs, operation,
intent, version, count, duration, outcome, and warning code. It must not contain
raw source, excerpts, user questions, prompts, model answers, secrets, or
absolute local paths. User-facing errors use stable codes without stack traces.

## Security Acceptance

- Fixture validation demonstrably does not execute repository code.
- Traversal, absolute Windows paths, backslashes, invalid lines, invented
  evidence, cross-repository evidence, and cross-snapshot evidence are rejected.
- Provider and network exposure remain absent by default and require explicit
  repository-level opt-in plus the Provider Opt-In Gate above.
- Any future change to these boundaries requires an ADR, security tests,
  rollback implications, and explicit user approval.

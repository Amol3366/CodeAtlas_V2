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

## Provider Opt-In Gate

Provider use is prohibited until all of the following are recorded for the
repository: provider identity and purpose, content classes permitted, explicit
user consent, secret/redaction policy, token and cost limits, timeouts,
cancellation, telemetry without content, deterministic fallback, and a
revocation path. Credentials never appear in GET responses, browser storage,
history exports, logs, or diagnostic bundles.

## Logging and Diagnostics

Default telemetry may contain opaque repository/snapshot/request IDs, operation,
intent, version, count, duration, outcome, and warning code. It must not contain
raw source, excerpts, user questions, prompts, model answers, secrets, or
absolute local paths. User-facing errors use stable codes without stack traces.

## Security Acceptance

- Fixture validation demonstrably does not execute repository code.
- Traversal, absolute Windows paths, backslashes, invalid lines, invented
  evidence, cross-repository evidence, and cross-snapshot evidence are rejected.
- Provider and network exposure remain absent in Phase 0.
- Any future change to these boundaries requires an ADR, security tests,
  rollback implications, and explicit user approval.

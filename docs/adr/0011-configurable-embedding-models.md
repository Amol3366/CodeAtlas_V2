# ADR-0011: Embedding model identity is configurable through `.env`

Status: accepted
Date: 2026-08-01
Phase: 7 (post-gate)
Amends: ADR-0009 decision 4. Does **not** supersede it.

## Context

ADR-0009 decision 4 pinned `LOCAL_MODEL_ID` and `OPENAI_MODEL_ID` as constants.
The reasoning is still in the source:

> Pinned, per ADR-0009 decision 4: the model ID is recorded on every embedding
> record, and changing it changes the similarity space. A float here would
> silently mix vectors from two models the first time the upstream default
> moved.

That reasoning is about **silent** change — an upstream default moving
underneath the product, with the recorded identity unchanged. It was never an
argument that a user must not choose a model.

Meanwhile the product could not be configured at all. `OpenAIEmbeddingProvider`
read `OPENAI_API_KEY` from the process environment, so a workstation user had
to export a machine-wide variable before the settings surface would even offer
OpenAI. Both provider constructors already accepted a `model_id` override and
nothing ever passed one. "Use a different open-source embedding model" required
editing source.

## Decision

Model identity becomes configurable through the environment, supplied by a
`.env` file read from the CodeAtlas root:

| Variable | Effect |
| --- | --- |
| `OPENAI_API_KEY` | The credential. Universal name, unchanged. |
| `CODEATLAS_OPENAI_EMBEDDING_MODEL` | OpenAI embedding model. Defaults to the pinned `text-embedding-3-small`. |
| `CODEATLAS_OPENAI_EMBEDDING_DIMENSIONS` | Vector width. **Required** when the model above is not the default. |
| `CODEATLAS_LOCAL_EMBEDDING_MODEL` | sentence-transformers model. Defaults to the pinned `all-MiniLM-L6-v2`. |

The pinned values remain the defaults. An installation that configures nothing
behaves exactly as it did before.

Precedence is **real environment > `.env` > pinned default**, implemented by
applying values only where the environment has none. A stale file can never
outrank a deliberate export.

## Why this is safe

The hazard ADR-0009 guarded against was an identity that changed *without the
namespace changing*. That cannot happen here.

`embedding_namespace_id` derives the namespace from
`(model_id, dimensions, normalization_version)`. A configured model change
therefore produces a **different namespace**, and per ADR-0010 a repository
points at one namespace. Vectors from two models cannot land in one similarity
space; the new model starts an empty one. P7-09's shadow-migration machinery
already moves a repository between namespaces with backfill, atomic cutover,
and rollback — which is exactly the operation a deliberate model change needs.

So configuration makes visible and reversible the thing ADR-0009 wanted never
to happen invisibly.

## The one place it is not free

OpenAI's vector width cannot be discovered without a billable API call, and
`OpenAIEmbeddingProvider.dimensions` was a constant `1536`. Pointing the model
at `text-embedding-3-large` while the width still read 1536 would write
3072-float vectors into a namespace labelled 1536 — a corrupted similarity
space that raises nothing and surfaces months later as poor results.

Therefore a non-default OpenAI model **must** declare
`CODEATLAS_OPENAI_EMBEDDING_DIMENSIONS`, and construction raises
`ProviderUnavailableError` naming the variable when it does not. A width that
disagrees with the default model is refused for the same reason: CodeAtlas does
not send OpenAI's `dimensions` request parameter, so such a value would be a
label rather than a request.

The local provider needs no equivalent. `_embedding_dimension` already asks the
loaded model its width, which costs nothing. The asymmetry is deliberate, not
an oversight.

## Consequences

- **`.env` supplies credentials and model identity, never consent.** Whether a
  repository may transmit stays in `repository_provider_policy` in SQLite, per
  repository, set through the settings surface. `build_embedding_provider`'s
  docstring already stated there is deliberately no environment override for
  it; that remains true and is asserted by
  `tests/security/test_env_configuration.py`.
- **The current working directory is never searched.** The file is read from
  `$CODEATLAS_ENV_FILE` or from the CodeAtlas root resolved through the
  package's own location. A current-directory search would let a repository
  you merely index configure the tool that indexes it, inverting `CLAUDE.md`
  Section 4.4.
- **`.env`, `.env.*`, and `*.env` join the default ignore patterns**, with
  `!.env.example` re-including the committed template. This is blueprint §8.11
  conformance and hygiene for a design that puts a credential file at a project
  root — explicitly **not** the closing of a leak. A `.env` classifies as
  `unknown` with no parser, so its contents were never parsed, chunked, written
  to FTS, or embedded; only its path was searchable.
- **No new runtime dependency.** The parser is ~40 lines of stdlib, matching the
  repository's existing choices (a hand-rolled YAML line scanner, stdlib
  `tomllib` only) which exist to keep untrusted-input parsers small and
  auditable.
- No schema change, no migration, no REST contract change. `ModelDescriptor`
  already typed `model_id` and `dimensions` as optional, so reporting a
  configured identity needed no contract movement.

## Alternatives rejected

- **`CODEATLAS_OPENAI_API_KEY` with a fallback to `OPENAI_API_KEY`.** Two names
  for one secret, and a precedence rule to document and test, for no benefit
  over the name every other tool already uses.
- **`.env` winning over the real environment.** A forgotten file would silently
  beat a deliberate export, and CI could not override a checked-out file.
- **Probing the API for the vector width.** One billable call per provider
  construction, on a path that constructs per index and per query.
- **`python-dotenv`.** A dependency for forty lines, against a repository
  pattern of hand-rolling exactly this kind of parser.
- **Making OpenAI the default provider.** `CLAUDE.md` §25 lists "repository
  content transmission enabled by default" as requiring explicit approval. Not
  requested, not done.

## Out of scope, recorded so they are decisions rather than omissions

- **OpenAI-compatible base URLs** (Ollama, LM Studio, vLLM as embedding
  backends). The cheapest path to open-source models and worth doing later, but
  it makes `transmits_off_machine` — currently a per-provider-kind constant —
  depend on a URL. A privacy label that can be wrong in the reassuring
  direction is worse than no feature.
- **LLM answer generation.** Only `NoAnswerProvider` exists. Phase 7 recorded
  generation as `declined` and the threat model lists concrete answer providers
  as "not shipped", pending a governed answer-provider policy and measured
  uplift. Shipping it needs its own ADR, evaluation, and approval.

# Evidence-grounded answer generation

Date: 2026-08-02
Status: approved by the user 2026-08-02
Policy authority: `AGENTS.md` / `CLAUDE.md`
Related: ADR-0009 (measured semantic uplift), `docs/security/threat-model.md`,
`docs/superpowers/specs/2026-08-01-env-provider-configuration-design.md` (which
recorded answer generation as out of scope, "pending a governed answer-provider
policy and measured uplift" — this design is that follow-up)

## Problem

Asked "Give me a full explanation about Prelegal project", CodeAtlas retrieves
the right evidence — the project's `CLAUDE.md` overview, `README.md`,
`main.py`, `llm.py` — and then renders 25 lines of the form:

> `CLAUDE.md` lines 1-2 contain text matching 'Give me a full explanation about
> Prelegal project'. [1]

The references are correct. Nothing reads them and answers the question. The
product is intended for "everyone who wants to know what is inside those codes
and documents", and a list of line ranges does not serve that reader.

Three verified causes, none of which is a defect:

1. **No model exists in the codebase.** The only `AnswerProvider` implementation
   is `NoAnswerProvider` (`generation/providers.py:60`), whose `generate()`
   returns `None`. Ollama and OpenAI answer providers were never written.
2. **The seam is never connected.** `build_services()` accepts an `explainer`
   parameter, but `api/app.py:284`, `cli/main.py:154`, and `mcp/server.py:51`
   all call it without one. `explainer=` is passed only in tests.
3. **Answers come from templates.** `conversations/templates.py` states the rule
   in its own docstring: "Prose around those values is written here, in this
   file, by us."

Phase 7 recorded generation as `declined by A/B measurement`. That is true and
misleading in equal measure: the A/B compared `NoAnswerProvider` against the
deterministic baseline. A provider that returns nothing improves nothing. **The
decision was never tested against a real model.**

Phase 7 built the seam and left it empty. This design fills it.

## Scope

**In:** three answer providers behind the existing `AnswerProvider` protocol
(`none`, Ollama, OpenAI), selected per repository through settings; token
streaming to the browser; situation-specific failure reporting; redaction,
budgets, and telemetry on the transmitting path.

**Out, as recorded decisions rather than omissions:**

- **Re-running the Phase 7 explanation A/B.** This design gives that evaluation
  something real to measure; running it is separate work, and `NoAnswerProvider`
  remains the default, so the recorded `declined` result stays factually true.

  This needs stating precisely, because `docs/security/threat-model.md:177`
  requires "a governed answer-provider policy **and** measured uplift before
  admission". This design delivers the policy, not the measurement. It resolves
  the tension by **not admitting the feature**: `answer_provider` defaults to
  `none`, the Phase 7 status stays `declined`, and the threat-model row moves
  from "not shipped" to "available, opt-in, uplift unmeasured" rather than to
  "admitted". A user switching it on for one repository is exercising an opt-in,
  not clearing a release gate. Admission still requires the A/B.
- **Changing retrieval.** Primary evidence Recall@10 is 0.6667 against a ≥ 0.90
  target (`docs/evaluation/phase-7-baseline-environment.md`). Prose over
  wrongly-retrieved evidence is worse than a list over it, because it reads as
  confident. Retrieval quality is a separate problem and is not improved here.
- **A `narrative` contract field.** Considered and rejected: `answer.summary` is
  already the prose slot, and a second field would bump `contract_version` and
  make every answer show two summaries saying similar things.

## The line this design will not cross

**Deterministic facts stay deterministic.** Today's `explain()` replaces
`answer.claims` with model-written claims tagged `model_generated` at 0.6
confidence. Applied to every intent — as this design does — that would relabel a
proven call-graph result as model output. It will not. The model writes
`answer.summary`; `answer.claims` and `answer.evidence` pass through untouched,
keeping their original derivation and confidence.

**Generation failure never fails a run.** Every fault falls back to the verified
answer with its citations, exactly as indexing already treats embedding failure:
a warning, never a failed snapshot.

**An abstention is never dressed up.** When there is no evidence, no model is
called and the response returns unchanged. "What CodeAtlas does not know" is one
of the product's five questions, and prose is the easiest way to lose it.

**`.env` still supplies no consent.** Whether a repository may transmit stays in
SQLite, per repository. No variable added here can turn a `none` repository into
a transmitting one.

## Approved decisions

| Decision | Choice |
| --- | --- |
| Provider | All three — `none` (default), Ollama, OpenAI — chosen in settings |
| Scope of generation | Every intent, not only conceptual ones |
| Trust model | Prose on top; claims and evidence untouched |
| Failure reporting | Situation-specific cause, always with the verified answer |
| Delivery | Token-by-token streaming |

The scope decision carries a cost the user accepted knowingly: a slow local
model adds latency to lookups that were previously instant. Recorded under
Limitations, and reversible by restoring the intent gate.

## Architecture

Approach: extend the existing explainer seam. Rejected alternatives were
generating in `RunExecutor` (chat would get prose; CLI, `/v1/query`, and MCP
would not — answer construction in two places that drift) and adding a contract
field (see Scope).

**New files**

| File | Purpose |
| --- | --- |
| `generation/prompts.py` | System prompt and evidence serialization. Repository content framed as data, never instruction. |
| `generation/ollama_provider.py` | `OllamaAnswerProvider` over local HTTP. |
| `generation/openai_provider.py` | `OpenAIAnswerProvider`, reachable only through governance. |
| `generation/factory.py` | Resolves a repository's setting to a provider, or `NoAnswerProvider`. |

**Changed files**

- `generation/providers.py` — a streaming method on the `AnswerProvider`
  protocol, and typed failure causes.
- `generation/explanations.py` — preserve claims instead of replacing them;
  accept a token callback.
- `conversations/pipeline.py` — remove the `GENERATION_INTENTS` gate; thread the
  existing `on_event` callback into the explainer; `generation.delta` starts
  carrying `{"text": chunk}`.
- `application/container.py` — build the explainer from the factory.
- `application/settings.py` and migration `0013` — per-repository settings.

**The structural subtlety.** `AnswerPipeline` is constructed per request, before
the repository is known — it arrives inside `AnswerRequest`. The explainer
therefore resolves a provider per call from `response.repository_id`, not at
construction. `SemanticFusionService` already does this
(`application/semantic_fusion.py:101,120,280`); this follows that pattern rather
than inventing one.

**No frontend work.** The streaming path is already complete end to end: the
contract defines `GENERATION_DELTA` (`contracts.py:584`), the service maps it
(`conversation_service.py:87`) and publishes payloads verbatim (line 544), and
`Thread.tsx:235-240` accumulates `payload["text"]`. The only gap is that
`pipeline.py:210` emits `{"length": ...}` and never `text`.

## Data flow

Steps 1-3 are unchanged; step 4 onward is new.

1. Intent classified, evidence retrieved and validated against the active
   snapshot.
2. Optional semantic candidates fused.
3. Deterministic claims built with their derivation labels.
4. The explainer reads the repository's `answer_provider` setting. `none`
   returns the response as-is.
5. Empty evidence returns the response as-is. No model call.
6. A prompt is built from validated evidence only, after redaction.
7. Tokens stream through `on_event` → `generation.delta` → SSE → browser.
8. On completion the text is validated and replaces **only** `answer.summary`.

Streamed text is provisional; if the finished text fails validation it is
replaced by the verified answer plus a warning. The contract already states this
("Streaming text is provisional. The final persisted response is
authoritative."), so the correction is a specified behavior rather than a
surprise.

## Settings and privacy

A per-repository `answer_provider` setting (`none` | `ollama` | `openai`), a
model name, and an optional token budget. Default `none`, so no existing
repository changes behavior until switched on.

Selecting `openai` requires the same explicit per-repository opt-in embeddings
require, because it transmits source. The OpenAI provider is wrapped in the
`GovernedEmbeddingProvider` pattern — redact, check budget, call with bounded
retries, record usage — so there is no unwrapped path to a transmitting model.

**Redaction applies to both providers.** Evidence excerpts are raw source and
raw source contains secrets. Ollama skips the budget check, not the redaction: a
local model can still write a secret into an answer that is then pasted
elsewhere.

**Prompt injection is a live concern here, not a theoretical one.** The indexed
`Prelegal` repository contains a `CLAUDE.md` written to instruct AI agents, and
chunks of it will be sent to a model as evidence. The system prompt states that
repository content is evidence, never instruction, and that only supplied
evidence IDs may be cited.

Telemetry records model, tokens, latency, and outcome. Never the prompt, the
evidence, or the answer.

## Error handling

| Cause | Warning code | Message |
| --- | --- | --- |
| Ollama down, connection refused | `GENERATION_PROVIDER_UNREACHABLE` | Can't connect to the model |
| Model not pulled or unknown | `GENERATION_MODEL_MISSING` | There is no model working |
| OpenAI key invalid | `GENERATION_KEY_REJECTED` | The API key was rejected |
| OpenAI quota exhausted | `GENERATION_QUOTA_EXHAUSTED` | The API key's quota is exhausted |
| Configured budget hit | `PROVIDER_BUDGET_EXCEEDED` (exists) | Monthly budget reached |
| Model too slow | `GENERATION_TIMED_OUT` | The model took too long to respond |
| Cited non-existent evidence | `GENERATED_CLAIM_INVALID` (exists) | Summary discarded, verified answer shown |
| Anything unanticipated | `ANSWER_GENERATION_FAILED` (exists) | Generic fallback |

Telling these apart requires inspecting provider responses rather than catching
a blanket `Exception`: Ollama returns 404 with a distinguishing body for a
missing model; OpenAI returns 401 for a bad key and 429 with `insufficient_quota`
for exhausted billing.

## Testing

- **Unit** — each cause maps to its warning; the summary is replaced while
  claims and evidence survive byte-identical; empty evidence produces no call.
- **Integration** — a fake provider drives the real pipeline: prose appears,
  claims keep their original derivation, and a provider citing a fabricated
  evidence ID has its output discarded.
- **Security** — a fake key inside an excerpt is redacted before send; a fixture
  containing injection text does not change behavior; the usage table still has
  no column content would fit in.
- **Contract** — `contract_version` stays `1.1`; `generation.delta` carries
  `text`; the response validates unchanged.
- **Fallback** — with `answer_provider = none` the entire existing suite passes
  untouched. This is the regression guard for the current product.

## Limitations recorded

- Generating on every intent adds model latency to lookups that were instant.
  Reversible by restoring the intent gate.
- This design does not improve retrieval. When the wrong evidence is retrieved,
  prose will state the wrong thing fluently.
- The Phase 7 explanation A/B is not re-run here, so the recorded `declined`
  result stands until it is.

## Follow-ups

- **ADR-0012** recording the governed answer-provider policy, as the `.env`
  spec required before shipping generation.
- **`docs/security/threat-model.md`** lists concrete answer providers as "not
  shipped" (line 177) and generated explanations as `declined` (line 176). Both
  rows must be updated in the same change: to "available, opt-in, uplift
  unmeasured" and left at `declined` respectively, per the Scope note above.
- **The Phase 7 explanation A/B**, run against a real provider, is what would
  change the admission status. Until then no phase gate or baseline is amended.

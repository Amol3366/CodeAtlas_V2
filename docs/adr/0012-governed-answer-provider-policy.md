# ADR-0012: Answer generation is prose over untouched evidence, opt-in and unadmitted

Status: accepted
Date: 2026-08-02
Phase: 7 (post-gate)
Amends: ADR-0009's explanation seam. Does **not** supersede it.
Design: `docs/superpowers/specs/2026-08-02-evidence-grounded-answer-generation-design.md`

## Context

Phase 7 built the `AnswerProvider` seam and left it holding only
`NoAnswerProvider`. Three things followed, none of them a defect and all of
them invisible from outside:

- the only implementation returned `None`, so no prose was ever produced;
- `build_services` accepted an `explainer` and no adapter passed one, so the
  seam was unreachable even had a provider existed;
- answers were rendered by `conversations/templates.py`, whose docstring states
  the arrangement plainly: "Prose around those values is written here, in this
  file, by us."

The user-visible result: asked "give me a full explanation of this project",
CodeAtlas retrieved the right evidence — the project's own overview documents,
its entry point, its main modules — and rendered twenty-five lines of the form
"`FILE` lines N-M contain text matching '\<the entire question\>'". The
references were correct. Nothing read them and answered.

Phase 7 recorded generated explanations as `declined by A/B measurement`. That
is true and easy to misread: the A/B compared `NoAnswerProvider` against the
deterministic baseline. A provider that returns nothing improves nothing. The
decision was never tested against a real model.

`docs/security/threat-model.md` listed concrete answer providers as "not
shipped", pending "a governed answer-provider policy and measured uplift before
admission". This ADR is that policy. It is deliberately not that measurement.

## Decision

**1. Generation replaces prose, never findings.** The model writes
`answer.summary`. `answer.claims` and `evidence` pass through untouched with
their original derivation and confidence.

The alternative — the behaviour the seam originally had — replaced claims with
model-written ones tagged `model_generated` at 0.6 confidence. That was
defensible while generation was gated to conceptual intents. It is not
defensible now that generation runs on every intent: a traced call graph would
be relabelled as something a model said. Structured findings stay
authoritative; natural-language explanation stays a derived view.

**2. Every intent is eligible, and the asymmetry with retrieval is the point.**
`SEMANTIC_INTENTS` still gates the *retrieval* channel, because a similarity
score must not choose the evidence a deterministic answer rests on. Generation
has no such gate, because by decision 1 it cannot change what an answer rests
on — only how it reads. Generating over an exact lookup costs latency, never
accuracy.

**3. A local model is primary.** `llama3.2:3b` on Ollama is the recommended and
pre-selected choice. It is the only default consistent with the product's first
sentence: source code does not leave the workstation. OpenAI remains available
for users who want stronger reasoning and accept the trade, exactly as it is
for embeddings.

**4. The default is off.** `answer_provider` defaults to `none`. Ollama is a
separate install, so a default-on setting would report "can't connect to the
model" on every question for every user who has not installed it — and would
declare the feature admitted without the measurement below. `embedding_provider`
already defaults to `none` for the same reason.

**5. Failure names its cause and never fails the run.** Six distinguished
causes (unreachable, model missing, key rejected, quota exhausted, timed out,
generic) each fall back to the verified answer with a warning. The remedies
differ — start a service, pull a model, add credit, wait — and a user told only
"generation failed" has to guess which one they have. Empty evidence produces
no provider call, so an abstention is never dressed up in prose.

**6. The timeout is configurable.** A 3B model answers in seconds; a 14B model
on a CPU can take minutes. A bound tuned to the default would turn "use a
bigger model for deeper reasoning" into a timeout on every question — the
feature appearing broken exactly when used as intended. Section 10.3 still gets
its bound; the user can raise it.

**7. Redaction applies to both providers.** Evidence excerpts are raw source
and raw source contains secrets. The local provider transmits nothing, but a
local model can still write a secret into an answer that is pasted into a
ticket. Only the prompt is redacted; the response keeps its real excerpts,
because the evidence drawer shows the user their own file.

**8. `.env` supplies model identity, never consent.** The stored per-repository
policy is the only thing that decides whether generation happens. This extends
ADR-0011's boundary to the answering path unchanged.

**9. The feature ships available, not admitted.** The Phase 7 explanation A/B
is not re-run here, so `docs/evaluation/explanation-phase-7.{json,md}` stands
and the recorded `declined` status is unchanged. The threat-model row moves
from "not shipped" to "available, opt-in, uplift unmeasured" — not to
"admitted". A user switching it on for one repository is exercising an opt-in,
not clearing a release gate.

## Consequences

Answer models are stateless, which makes them unlike every other model decision
in this product. Changing an *embedding* model invalidates the vector index and
requires a shadow namespace, a backfill, and an atomic cutover (ADR-0010,
ADR-0011). An answer model stores nothing: it reads verified evidence and
writes prose. Changing it affects the next answer and nothing else — no
migration, no rollback window, no ceremony. Users can experiment freely, and
the implementation deliberately builds none of the machinery the embedding side
needs.

Migration `0013` adds three nullable-or-defaulted columns, so an existing
database upgrades to exactly its current behaviour. `SCHEMA_VERSION` moves
12 → 13.

Two limitations are recorded rather than discovered later. Generating on every
intent adds model latency to lookups that were previously instant; restoring
the intent gate reverses it. And this design does not improve retrieval —
primary evidence Recall@10 remains 0.6667 against a ≥ 0.90 target
(`docs/evaluation/phase-7-baseline-environment.md`), so when the wrong evidence
is retrieved, prose will now state the wrong thing fluently rather than listing
it. That is a real regression in the *appearance* of confidence, and the reason
decision 1 keeps citations underneath every generated paragraph.

## Section 25 review

| Item | Triggered? |
| --- | --- |
| Mandatory cloud dependency | No. Default is `none`; the recommended provider is local |
| Repository content transmitted by default | No. Transmission requires selecting `openai` per repository, which additionally requires a monthly budget |
| LLM authority over deterministic findings | **No, and decision 1 is what prevents it.** Claims and evidence are untouched; the model writes prose only |
| Breaking API / contract change | No. `contract_version` stays `1.1`; settings and `/v1/models` additions are additive |
| New primary database, service, or language | No |

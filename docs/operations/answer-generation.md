# Answer generation

CodeAtlas finds evidence and cites it. Answer generation adds a written
explanation on top of that evidence. It is optional, off by default, and
changes nothing about how evidence is found or verified.

Policy: ADR-0012. Design:
`docs/superpowers/specs/2026-08-02-evidence-grounded-answer-generation-design.md`.

## What it changes, and what it does not

**Changes:** the summary paragraph at the top of an answer.

**Does not change:** the claims beneath it, their citations, their line
numbers, their derivation labels, or their confidence. Ask "who calls X" with
generation on and the call graph is still traced deterministically — a model
writes the paragraph above it, never the result itself.

That boundary is the reason generation is allowed to run on every question. If
the model produced the findings, a traced call graph would arrive labelled as
something a model said. It does not.

## Turning it on

1. Install Ollama from <https://ollama.com/download>.
2. Pull the default model, or let Settings request the same download after you
   select Ollama:

   ```powershell
   ollama pull llama3.2:3b
   ```

3. Open Settings, choose **Ollama (local, recommended)** under *Answer
   provider*, and save. The model must already be pulled — step 2 above.

Nothing leaves your machine. Ollama runs locally and CodeAtlas talks to it on
loopback.

To use OpenAI instead, select it and set a monthly token budget — CodeAtlas
refuses to enable a transmitting provider without a spending bound. That
choice sends evidence excerpts to OpenAI. Excerpts are redacted first, but
redaction is a safety net, not a guarantee about your source.

## Choosing a different model

`llama3.2:3b` is small: about 2 GB, fast on modest hardware, and it summarizes
clearly rather than reasoning deeply across many files. For subtler questions,
a larger model is a one-field change.

Pull it, then type its tag into **Answer model** in Settings:

```powershell
ollama pull llama3.1:8b
```

Bigger models need proportionally more memory and answer more slowly. The tag
must be one Ollama has actually pulled — a tag it does not have reports "there
is no model working", not a silent fallback.

CodeAtlas does not run the pull for you. Settings names the model and shows the
command; you run it in a terminal, where its progress and its failures are
legible. A pull is a multi-gigabyte network operation, and putting it behind a
button in a settings form makes a slow or failed download look like a failed
save.

Swapping answer models is free. Unlike an embedding model, an answer model
stores nothing: changing it affects the next answer and nothing else. No
re-index, no migration, no rollback window.

### Machine-wide defaults

`.env` sets defaults for every repository; the Settings field overrides them
per repository.

| Variable | Default |
| --- | --- |
| `CODEATLAS_OLLAMA_ANSWER_MODEL` | `llama3.2:3b` |
| `CODEATLAS_OLLAMA_BASE_URL` | `http://127.0.0.1:11434` |
| `CODEATLAS_OPENAI_ANSWER_MODEL` | `gpt-4o-mini` |
| `CODEATLAS_ANSWER_TIMEOUT_SECONDS` | `120` |

None of these enables generation. Whether a repository generates is stored per
repository and set in the app.

**Raise the timeout when using a large local model on a CPU**, where a single
answer can take minutes. A bound tuned to the 3B default would make every
question fail once you switch to something bigger.

## When it does not work

Generation never fails a question. You always get the verified answer and its
citations; only the paragraph is missing, and the warning says why.

| Warning | Meaning | What to do |
| --- | --- | --- |
| `GENERATION_PROVIDER_UNREACHABLE` | Nothing answered on the port | Start Ollama, or check `CODEATLAS_OLLAMA_BASE_URL` |
| `GENERATION_MODEL_MISSING` | Ollama is running but lacks that model | `ollama pull <tag>`, or correct the tag in Settings |
| `GENERATION_KEY_REJECTED` | OpenAI refused the credential | Check `OPENAI_API_KEY` in `.env` |
| `GENERATION_QUOTA_EXHAUSTED` | The OpenAI account has no credit | Add credit, or switch to Ollama |
| `PROVIDER_BUDGET_EXCEEDED` | Your configured monthly budget is spent | Raise the budget in Settings, or switch to Ollama |
| `GENERATION_TIMED_OUT` | The model did not finish in time | Raise `CODEATLAS_ANSWER_TIMEOUT_SECONDS`, or use a smaller model |
| `GENERATED_CLAIM_INVALID` | The model cited evidence that does not exist | Nothing — the summary was discarded on purpose |
| `ANSWER_GENERATION_FAILED` | Something else went wrong | Check that the provider is healthy |

A question with **no** evidence produces no model call at all. CodeAtlas says
what it could not find rather than writing prose about nothing.

## Privacy

- Evidence excerpts are redacted before any provider sees them — including the
  local one, because a local model can still write a secret into an answer you
  paste elsewhere.
- Only the prompt is redacted. The evidence drawer keeps showing your real
  file, which is on your own machine.
- Telemetry records model, tokens, latency, and outcome. Never the prompt, the
  evidence, or the answer.
- Repository content is sent as evidence, never as instruction. The system
  prompt says so, and an indexed repository containing instructions aimed at AI
  agents is described rather than obeyed.

## Status: available, not admitted

Generation ships **opt-in with its uplift unmeasured**. Phase 7 recorded
generated explanations as `declined` after an A/B against `NoAnswerProvider` —
a provider that returns nothing, which improves nothing. That A/B has not been
re-run against a real model, so the recorded status stands.

Switching this on is you exercising an option, not CodeAtlas claiming a
measured improvement.

One limitation is worth stating plainly: **generation does not improve
retrieval.** Primary evidence Recall@10 is 0.6667 against a ≥ 0.90 target
(`docs/evaluation/phase-7-baseline-environment.md`). When the wrong evidence is
retrieved, a model will now describe the wrong thing fluently instead of
listing it. That is why the citations stay beneath every generated paragraph —
they remain the part you can check.

## Verified behaviour

Against Ollama 0.32.5 with `llama3.2:3b`, on a real indexed repository:

| Check | Result |
| --- | --- |
| Provider off | Deterministic answer unchanged, no warnings added |
| Provider on | Multi-paragraph prose with headings and lists |
| Claims after generation | 25 claims, derivation `high_confidence_heuristic` — unchanged |
| Evidence after generation | 25 items, unchanged |
| Streaming | 511 `generation.delta` events over SSE, 2,357 characters |
| Persisted answer | 8,573 characters, status `complete`, citations intact |
| Model missing | `GENERATION_MODEL_MISSING`, verified answer returned |
| Provider unreachable | `GENERATION_PROVIDER_UNREACHABLE`, verified answer returned |

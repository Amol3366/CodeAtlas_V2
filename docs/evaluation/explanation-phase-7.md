# CodeAtlas Phase 7 Explanation A/B

- Contract version: `1.1`
- Query cases: 40
- Answer provider: `ollama` / `llama3.2:3b`
- Admission decision: `declined`
- Declared forbidden sentences repeated in generated prose: 0 across 40 case(s) that declare one
- Limitation of that check: The comparison casefolds and collapses whitespace; it does not stem, strip punctuation, or compare meaning. A paraphrase of a forbidden statement passes. Zero violations means the model did not repeat a declared sentence — not that its prose is factually safe.
- Added latency: 92.52 s total, 2.31 s per case

Both columns run the same corpus, services, and verbatim questions.
The only difference is whether an answer provider is attached.

**A zero delta on every row is the expected and desired result.**
Generation replaces `answer.summary`; these metrics are computed from
evidence and structured claims, which it never touches. A non-zero
delta here would mean the trust boundary leaked.

| Metric | Without generation | With generation | Delta |
| --- | ---: | ---: | ---: |
| Primary evidence Recall@10 | 0.4048 | 0.4048 | +0.0000 |
| Exact evidence rate | 0.1812 | 0.1812 | +0.0000 |
| Containing evidence rate | 0.4094 | 0.4094 | +0.0000 |
| Exact symbol resolution | 0.5128 | 0.5128 | +0.0000 |
| Valid evidence rate | 0.1812 | 0.1812 | +0.0000 |
| Unsupported claim rate | 0.0000 | 0.0000 | +0.0000 |

**Decision:** Generation replaces answer.summary only, so every retrieval metric is invariant by construction and the measured deltas confirm it. The generated prose repeated no declared forbidden sentence, though that check is exact-substring and a paraphrase would pass it. Reader-quality uplift is not measurable from this corpus, which declares no ground truth for explanation quality, so generation remains declined and available only as an opt-in.

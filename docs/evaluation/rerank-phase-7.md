# CodeAtlas Phase 7 Rerank A/B

- Contract version: `1.0`
- Query cases: 18
- Change cases: 1
- Reranker: `none` / `none`
- Admission decision: `declined`
- Reason: No metric improved over the admitted semantic baseline; the only implemented reranker is identity.

The reranked column applies the only implemented P7-10 reranker, `NoReranker`, which preserves semantic candidate order and performs no provider call.

| Metric | Semantic | Reranked | Delta |
| --- | ---: | ---: | ---: |
| Primary evidence Recall@10 | 0.8421 | 0.8421 | +0.0000 |
| Exact evidence rate | 0.0654 | 0.0654 | +0.0000 |
| Containing evidence rate | 0.1154 | 0.1154 | +0.0000 |
| Exact symbol resolution | not applicable | not applicable | not applicable |
| Abstention correctness | 1.0000 | 1.0000 | +0.0000 |
| Unsupported claim rate | 0.0000 | 0.0000 | +0.0000 |

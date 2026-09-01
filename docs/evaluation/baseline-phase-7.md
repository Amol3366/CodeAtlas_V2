# CodeAtlas Phase 7 Semantic Uplift Baseline

- Contract version: `1.0`
- Query cases: 18
- Change cases: 1

Both columns are the same corpus through the same pipeline. The only
difference is whether a semantic fusion layer is attached.

| Metric | Deterministic | Semantic | Delta |
| --- | ---: | ---: | ---: |
| Primary evidence Recall@10 | 0.6842 | 0.8421 | +0.1579 |
| Containing evidence Recall@10 | 0.8947 | 1.0000 | +0.1053 |
| Exact evidence rate | 0.0854 | 0.0654 | -0.0200 |
| Containing evidence rate | 0.1341 | 0.1154 | -0.0188 |
| Exact symbol resolution | not applicable | not applicable | not applicable |
| Symbol Recall@10 | 0.7778 | 0.9444 | +0.1667 |
| Abstention correctness | 0.9444 | 1.0000 | +0.0556 |
| Unsupported claim rate | 0.0000 | 0.0000 | +0.0000 |

# CodeAtlas Phase 7 Semantic Uplift Baseline

- Contract version: `1.0`
- Query cases: 14
- Change cases: 1

Both columns are the same corpus through the same pipeline. The only
difference is whether a semantic fusion layer is attached.

| Metric | Deterministic | Semantic | Delta |
| --- | ---: | ---: | ---: |
| Primary evidence Recall@10 | 0.6000 | 0.8000 | +0.2000 |
| Containing evidence Recall@10 | 0.8667 | 1.0000 | +0.1333 |
| Exact evidence rate | 0.0741 | 0.0605 | -0.0136 |
| Containing evidence rate | 0.1259 | 0.1116 | -0.0143 |
| Exact symbol resolution | not applicable | not applicable | not applicable |
| Symbol Recall@10 | 0.7143 | 0.9286 | +0.2143 |
| Abstention correctness | 0.9286 | 1.0000 | +0.0714 |
| Unsupported claim rate | 0.0000 | 0.0000 | +0.0000 |

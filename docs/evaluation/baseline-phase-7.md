# CodeAtlas Phase 7 Semantic Uplift Baseline

- Contract version: `1.0`
- Query cases: 14
- Change cases: 1

Both columns are the same corpus through the same pipeline. The only
difference is whether a semantic fusion layer is attached.

| Metric | Deterministic | Semantic | Delta |
| --- | ---: | ---: | ---: |
| Primary evidence Recall@10 | 0.6000 | 0.6667 | +0.0667 |
| Exact evidence rate | 0.0752 | 0.0563 | -0.0188 |
| Containing evidence rate | 0.1278 | 0.1080 | -0.0198 |
| Exact symbol resolution | not applicable | not applicable | not applicable |
| Symbol Recall@10 | 0.7143 | 0.7857 | +0.0714 |
| Abstention correctness | 0.9286 | 1.0000 | +0.0714 |
| Unsupported claim rate | 0.0000 | 0.0000 | +0.0000 |

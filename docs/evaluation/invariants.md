# ADR-0016 invariants

A weak `TESTS` edge explains a gap rather than closing it.

Result: **held** (4/4 cases held)

| Case | Invariant | Held | Detail |
| --- | --- | --- | --- |
| i001 | a fixture-mediated symbol is explained, not covered | yes |  |
| i002 | a helper-mediated symbol is explained, not covered | yes |  |
| i003 | a strict import-and-call edge still closes a gap | yes |  |
| i004 | an unreferenced symbol reports bare absence | yes |  |

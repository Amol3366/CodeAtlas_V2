# Should Phase 4 be re-gated on the realistic performance profile?

A decision brief. Measured 2026-09-02 (RW-06). **This proposes no change to any
gate** — the scope decision is the user's.

## The two targets

Section 19.3 declares them, and `measure_phase4_perf.py` implements them:
**changed-file refresh p95 ≤ 2 s** and **preflight p95 ≤ 10 s**. The script
exits 1 if either misses.

## Why there are two profiles

ADR-0064 showed the synthetic tree **cannot contain the dominant cost**. Its
generated modules emit no documents that mention the symbols they define, so the
work a real repository does is structurally absent. `--profile realistic` was
added to emit that shape: documents mentioning the symbols, and modules with a
realistic body size.

The synthetic profile is kept **byte-identical** because the tracked Phase 4
baseline was taken on it.

## Measured

10 runs per point. Windows 11 (10.0.26200), Intel64 Family 6 Model 191, 24
logical CPUs, Python 3.12.12, on an otherwise idle machine.

| Modules | Profile | Refresh p95 | ≤ 2 s | Preflight p95 | ≤ 10 s |
| ---: | --- | ---: | :---: | ---: | :---: |
| 40 | synthetic | 0.406 | ✅ | 0.860 | ✅ |
| 40 | realistic | 1.376 | ✅ | 2.051 | ✅ |
| 80 | synthetic | 0.590 | ✅ | 1.205 | ✅ |
| 80 | **realistic** | **2.111** | ❌ | 3.794 | ✅ |
| 120 | synthetic | 0.781 | ✅ | 1.737 | ✅ |
| 120 | realistic | 3.187 | ❌ | 5.451 | ✅ |
| 160 | synthetic | 0.975 | ✅ | 2.001 | ✅ |
| 160 | realistic | 4.329 | ❌ | 7.268 | ✅ |
| 300 | synthetic | 1.799 | ✅ | 3.750 | ✅ |
| 300 | **realistic** | **9.427** | ❌ | **13.844** | ❌ |

**The register's claim is confirmed: refresh first misses at 80 modules.**

**A second miss the register does not record:** at 300 modules the realistic
profile also misses the **preflight** target — 13.844 s against 10 s. The
register described this as a refresh problem. It is both.

The gap widens with size — realistic/synthetic refresh is 3.4× at 40 modules and
5.2× at 300 — so it is not a constant offset that a one-off target adjustment
would absorb.

## Limits of this measurement

- **p95 over 10 runs is effectively the near-maximum.** That is adequate to
  locate a threshold crossing, which is what this brief is for. It is *not*
  adequate to publish as a headline figure, and none of these numbers should be
  copied into the README, which quotes 20-run measurements from
  `measure_phase7_perf.py`.
- One machine, one run each. No controlled pair, which the register already
  requires for any performance regression claim.
- The JSON outputs are deliberately **not committed**: they are
  machine-specific, and a tracked file here would read as a baseline.

## The options

**(a) Leave the gate; record the realistic figure beside it.**
The gate keeps measuring a reproducible synthetic tree, and the realistic number
is documented as a known limit. Honest, cheap, and changes nothing — but the
release gate goes on passing on a profile ADR-0064 showed cannot contain the
dominant cost.

**(b) Re-gate on realistic, and track a new baseline.**
Makes the gate measure the shape that matters. Costs: the realistic tree is not
currently tracked or reproducible the way the synthetic one is, so a baseline
has to be established first; and **the gate would fail today at 80 modules**, so
this is a decision to accept a red gate until the cost is fixed.

**(c) Re-gate on realistic and relax the target to what it supports.**

**This is the option ADR-0048 already refused** — *"a number chosen to be passed
says less than it appears to"* — and it is listed for completeness, not
neutrally. A ≤ 10 s refresh target chosen because 9.427 s is what the profile
happens to produce would describe the implementation, not a product commitment.
ADR-0032 and ADR-0033 both had to correct thresholds picked that way.

## What is not being claimed

That this is a regression. It is not: nothing got slower. The realistic profile
was added *because* the synthetic one was known to be unrepresentative, and it
is doing exactly what it was built to do. The question is only whether the
release gate should move to it.

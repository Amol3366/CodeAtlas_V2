"""Did the machine hold still while a performance run was measured?

`AGENTS.md` Section 19.3 requires a performance claim to name its hardware and
method. It says nothing about the machine's *state*, and on 2026-08-21 that gap
produced a published wrong result: packaged refresh p95 measured 2.407 s against
a <= 2 s target, was recorded as a missed release target, and was defended
because two runs agreed within 26 ms. On a quiet machine the same artifact
measured 1.759 s and 1.722 s -- agreeing within 37 ms, and passing. The observed
spread over one day was 1.413-2.433 s, wider than the threshold being compared
against.

**Two runs minutes apart share a machine state; they do not sample it.** So the
harnesses take a calibration probe before and after a measurement, record both,
and refuse when they disagree.

Scope, stated because it is easy to over-read:

* **Enforced:** the machine did not change speed *during* the run. That is
  checkable without knowing anything about the hardware -- if the probe moved,
  the early samples and the late ones came from different machines.
* **Recorded, not enforced:** how fast the machine is in absolute terms. The
  right threshold is hardware-specific and this project has no reference for the
  machines it might run on, so inventing one would be a number chosen to be
  passed (ADR-0032, ADR-0048). The probe duration goes into the artifact instead,
  so two runs can be compared for machine state by whoever reads them.

A constant background load therefore passes the drift check. That is a real
limit, and the recorded durations are what make it visible.
"""

from __future__ import annotations

import hashlib
import time

# How much the probe may move between the start and end of a run. Below this,
# ordinary scheduling noise; above it, the machine was doing something else for
# part of the measurement.
CALIBRATION_TOLERANCE = 0.20

# Enough work to be measurable against the OS clock without meaningfully adding
# to a multi-second run. CPU-bound and allocation-light on purpose: the thing
# being protected is a mix of parsing and SQLite, and a probe dominated by disk
# would report the page cache rather than the processor.
#
# Sized to run for roughly 0.2 s. Shorter was tried and rejected: at ~14 ms the
# probe can fall entirely inside a quiet slice of a busy machine and report calm
# that is not there. 0.2 s averages over scheduling while staying negligible
# against a multi-second measurement.
_PROBE_BLOCK = b"codeatlas-quiescence-probe" * 64
_PROBE_ROUNDS = 300_000


def calibrate() -> float:
    """Run a fixed workload and return how long it took, in seconds.

    Deterministic in the work performed, so two calls differ only by what else
    the machine was doing. The absolute value is meaningless across hardware and
    is never compared to a constant -- only to another reading from the same
    machine and the same run.
    """
    started = time.perf_counter()
    digest = hashlib.sha256()
    for _ in range(_PROBE_ROUNDS):
        digest.update(_PROBE_BLOCK)
    digest.hexdigest()
    return time.perf_counter() - started


def drift(before: float, after: float) -> float:
    """Relative disagreement between two probes, symmetric in its arguments.

    Divided by the smaller reading so that a doubling and a halving report the
    same amount of disagreement. A run that *sped up* is as untrustworthy as one
    that slowed: either way its samples were not taken on one machine.
    """
    if before <= 0.0 or after <= 0.0:
        return float("inf")
    return abs(after - before) / min(before, after)


def unsettled_reason(
    before: float, after: float, *, tolerance: float = CALIBRATION_TOLERANCE
) -> str | None:
    """Why this measurement should not be trusted, or ``None`` if it should.

    The message names both durations and the direction, because "the machine was
    busy" is not actionable and "it was 40% slower by the end" is.
    """
    moved = drift(before, after)
    if moved <= tolerance:
        return None
    direction = "slowed down" if after > before else "sped up"
    return (
        f"the machine {direction} during the run: calibration probe "
        f"{before:.3f} s before, {after:.3f} s after "
        f"({moved:.0%} drift, tolerance {tolerance:.0%}). "
        "Samples taken at the start and end are not comparable, so this run "
        "cannot decide a pass/fail. Re-measure on an idle machine."
    )

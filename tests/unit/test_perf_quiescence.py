"""A performance measurement declares whether the machine held still for it.

**This exists because of a wrong result that was published.** On 2026-08-21 the
packaged refresh p95 was measured at 2.407 s against a <= 2 s target, recorded
as a missed release target in the tracked artifact and the README, and defended
on the grounds that two runs agreed within 26 ms. Measured again on a quiet
machine the same day: **1.759 s and 1.722 s, agreeing within 37 ms, target met.**
The spread across one day, one machine and one artifact was **1.413-2.433 s** --
wider than the threshold it was being compared against.

**Within-session agreement was not evidence of anything.** Two runs minutes apart
share a machine state; they do not sample it. `measure_phase7_perf.py` stamps
`refresh_target_met` from whatever the machine could do at that moment, and that
field is quoted in `README.md` as a release figure.

So a run now carries a calibration probe taken **before and after** the
measurement, and refuses when the two disagree.

**What is enforced, and what is only recorded.** Drift between the two probes is
enforceable without knowing anything about the hardware: if the machine changed
speed *during* the run, the samples are not comparable to each other, whatever
box they were taken on. An **absolute** "is this machine fast enough" threshold
is deliberately **not invented**, because the right value is hardware-specific
and this project has no reference for the machines it might run on. The probe
duration is written into the artifact instead, so two runs can be compared for
machine state by anyone reading them -- which is the check that would have caught
the original error in seconds.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from codeatlas.evaluation.quiescence import (
    CALIBRATION_TOLERANCE,
    calibrate,
    drift,
    unsettled_reason,
)


def test_the_probe_reports_a_positive_duration() -> None:
    """The probe has to do enough work to be measurable."""
    elapsed = calibrate()
    assert elapsed > 0.0


def test_the_probe_is_deterministic_in_the_work_it_does() -> None:
    """Two probes measure the same workload, so their durations are comparable.

    Not an assertion about speed -- a loaded machine legitimately returns a
    larger number, which is the entire point. This pins that the *workload* does
    not vary, because a probe whose work differed run to run would report drift
    that was its own.
    """
    first, second = calibrate(), calibrate()
    assert first > 0.0 and second > 0.0
    # Same work, so the same order of magnitude even under moderate load.
    assert drift(first, second) < 10.0


def test_a_steady_machine_reports_no_reason() -> None:
    assert unsettled_reason(1.00, 1.05) is None


@pytest.mark.parametrize(
    ("before", "after"),
    [
        (1.00, 2.00),  # slowed down during the run
        (2.00, 1.00),  # sped up during the run -- equally disqualifying
    ],
)
def test_a_machine_that_changed_speed_is_refused(before: float, after: float) -> None:
    """Symmetric on purpose.

    A run that *sped up* is as untrustworthy as one that slowed: either way the
    early samples and the late ones were taken on different machines. The
    original defect was a whole run taken while the box was still busy after a
    test suite, which is exactly the "sped up" shape.
    """
    reason = unsettled_reason(before, after)
    assert reason is not None
    assert f"{before:.3f}" in reason and f"{after:.3f}" in reason, (
        "the reason must name both probe durations, or a reader cannot tell "
        "which direction the machine moved"
    )


def test_drift_is_symmetric() -> None:
    """Doubling and halving are the same amount of disagreement."""
    assert drift(1.0, 2.0) == pytest.approx(drift(2.0, 1.0))


def test_the_tolerance_is_stated_and_overridable() -> None:
    """A caller measuring something long may want a wider band.

    The default is what the harnesses use; it is a constant rather than a
    literal so the artifact and the docs can name the same number.
    """
    assert 0.0 < CALIBRATION_TOLERANCE < 1.0
    assert unsettled_reason(1.0, 1.5, tolerance=1.0) is None
    assert unsettled_reason(1.0, 1.5, tolerance=0.01) is not None


def test_the_phase7_harness_refuses_a_run_the_machine_moved_under(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The check is wired in, not merely available.

    `measure_phase7_perf.py` stamps `refresh_target_met` and that field is
    quoted in `README.md` as a release figure, so the refusal has to reach the
    exit code -- a helper nobody calls would have changed nothing on
    2026-08-21. Exit 2 is "blocked", matching the artifact-missing and
    provider-unavailable paths: the measurement is being reported on, not the
    product.
    """
    from scripts import measure_phase7_perf as harness

    artifact = tmp_path / "codeatlas.exe"
    artifact.write_bytes(b"not a real binary")
    output = tmp_path / "out.json"

    def moved_machine(*_args: object, **_kwargs: object) -> dict[str, object]:
        return {
            "calibration_before_s": 0.200,
            "calibration_after_s": 0.400,
            "refresh_p95_s": 2.407,
            "refresh_target_met": False,
            "preflight_p95_s": 4.376,
            "preflight_target_met": True,
            "semantic_coverage_target_met": True,
        }

    monkeypatch.setattr(harness, "_measure", moved_machine)
    code = harness.main(
        ["--artifact", str(artifact), "--json-output", str(output)]
    )

    assert code == 2, "a run the machine moved under must be blocked, not reported"
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["measurement_status"] == "blocked"
    assert payload["reason"] == "machine_not_settled"
    assert "refresh_target_met" not in payload, (
        "a blocked run must not publish a pass/fail verdict -- that is the "
        "defect this check exists for"
    )
    assert payload["measured_but_discarded"]["refresh_p95_s"] == 2.407, (
        "the discarded figures are kept so the run is diagnosable"
    )


def test_allow_busy_reports_the_figures_and_says_so(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An override exists, and it cannot be silent.

    Someone measuring on a machine they cannot quiesce needs a way through. The
    artifact records `machine_settled` either way, so the override is visible in
    the record rather than only in the shell that ran it.
    """
    from scripts import measure_phase7_perf as harness

    artifact = tmp_path / "codeatlas.exe"
    artifact.write_bytes(b"not a real binary")
    output = tmp_path / "out.json"

    def moved_machine(*_args: object, **_kwargs: object) -> dict[str, object]:
        return {
            "calibration_before_s": 0.200,
            "calibration_after_s": 0.400,
            "machine_settled": False,
            "refresh_p95_s": 1.5,
            "refresh_target_met": True,
            "preflight_p95_s": 3.0,
            "preflight_target_met": True,
            "semantic_coverage_target_met": True,
        }

    monkeypatch.setattr(harness, "_measure", moved_machine)
    code = harness.main(
        ["--artifact", str(artifact), "--json-output", str(output), "--allow-busy"]
    )

    assert code == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["machine_settled"] is False
    assert payload["refresh_target_met"] is True

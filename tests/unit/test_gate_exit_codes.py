"""A gate script states its verdict in its exit code.

Measured before this was written, because the Deferred Register's stated
mechanism turned out to be wrong. With `powershell -File`, a trailing native
command's non-zero `$LASTEXITCODE` does *not* become the process exit code --
the success path already exited 0. The real exposure is narrower: a caller that
reads `$LASTEXITCODE` after invoking the gate (a wrapper script, a CI step,
another .ps1) sees the stale code of whatever the gate ran last.

The safety property is the one worth pinning hardest: because
`$ErrorActionPreference = "Stop"` and `Invoke-Checked` throws, a failing step
terminates the script before it can reach the trailing `exit 0`. The line
cannot convert a red gate into a green one, and
`test_a_failing_step_still_exits_non_zero_despite_the_trailing_exit` is what
keeps that true.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

SCRIPTS = Path("scripts")

_WINDOWS_ONLY = pytest.mark.skipif(
    os.name != "nt",
    reason="PowerShell exit-code semantics are the Windows behaviour under test",
)


def _gate_scripts() -> list[Path]:
    found = sorted(SCRIPTS.glob("check_phase*.ps1"))
    assert found, "no gate scripts found; the guard would pass vacuously"
    return found


def _last_statement(script: Path) -> str:
    lines = [
        stripped
        for line in script.read_text(encoding="utf-8").splitlines()
        if (stripped := line.strip()) and not stripped.startswith("#")
    ]
    return lines[-1]


@pytest.mark.parametrize("script", _gate_scripts(), ids=lambda p: p.name)
def test_every_gate_script_ends_by_exiting_zero(script: Path) -> None:
    """All eight, not just the one the register named.

    A guard carrying an exemption list is weaker than the rule it encodes, and
    invites the next script to be added broken.
    """
    assert _last_statement(script) == "exit 0", (
        f"{script.name} does not end with an explicit `exit 0`, so a caller "
        "reading $LASTEXITCODE gets whatever its last native command left."
    )


def _run_script(script: Path) -> int:
    completed = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script),
        ],
        capture_output=True,
        text=True,
        cwd=script.parent,
    )
    return completed.returncode


_TRAILING_FAILURE = (
    '$ErrorActionPreference = "Stop"\n'
    'cmd /c "exit 3"\n'
    'Write-Output "verification completed."\n'
)

_WRAPPER = (
    '$ErrorActionPreference = "Stop"\n'
    '& "./gate.ps1"\n'
    "exit $LASTEXITCODE\n"
)


@_WINDOWS_ONLY
def test_a_caller_reading_lastexitcode_sees_a_stale_code_without_the_line(
    tmp_path: Path,
) -> None:
    """Why the line is worth adding at all.

    The wrapper is the shape that exposes it: `-File` on its own returns 0 here,
    which is exactly why this went unnoticed.
    """
    (tmp_path / "gate.ps1").write_text(_TRAILING_FAILURE, encoding="utf-8")
    wrapper = tmp_path / "wrapper.ps1"
    wrapper.write_text(_WRAPPER, encoding="utf-8")

    assert _run_script(wrapper) == 3


@_WINDOWS_ONLY
def test_the_trailing_exit_zero_stops_the_stale_code_reaching_the_caller(
    tmp_path: Path,
) -> None:
    (tmp_path / "gate.ps1").write_text(
        _TRAILING_FAILURE + "exit 0\n", encoding="utf-8"
    )
    wrapper = tmp_path / "wrapper.ps1"
    wrapper.write_text(_WRAPPER, encoding="utf-8")

    assert _run_script(wrapper) == 0


@_WINDOWS_ONLY
def test_a_failing_step_still_exits_non_zero_despite_the_trailing_exit(
    tmp_path: Path,
) -> None:
    """The safety property. Without this, the fix could hide a red gate.

    `Invoke-Checked` throws on a non-zero step and `$ErrorActionPreference` is
    `Stop`, so the script terminates above the trailing line and never runs it.
    """
    gate = tmp_path / "gate.ps1"
    gate.write_text(
        '$ErrorActionPreference = "Stop"\n'
        'throw "step failed"\n'
        'Write-Output "verification completed."\n'
        "exit 0\n",
        encoding="utf-8",
    )

    assert _run_script(gate) == 1

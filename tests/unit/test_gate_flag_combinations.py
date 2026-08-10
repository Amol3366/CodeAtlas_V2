"""A gate flag never silently cancels work another flag asked for.

`check_phase7.ps1 -SkipWeb -Perf` **exited 0 having measured nothing.**
`-SkipWeb` does not skip the web section -- it `exit 0`s the script, meaning
"backend checks only, then stop" -- and the `-Perf` block sits a hundred lines
below that exit. A releaser following `docs/operations/release-validation.md`
step 3 got a green run and no measurement.

That is the dangerous shape. The sibling defect found the same day
(`-Package` failing to bind, see `test_gate_script_invocations.py`) at least
*failed loudly*. This one passes.

The rule enforced here: if a script can exit early on flag ``A``, and a block
gated on flag ``B`` sits after that exit, then ``-A -B`` is a combination the
script cannot honour -- so the script MUST refuse it up front rather than
quietly doing less than it was asked.

Refusing matches what these scripts already do elsewhere. `check_phase7.ps1`'s
own comment on the performance step says it "refuses to substitute a
deterministic-only number when the local model or the semantic package build is
missing". Silently skipping is the thing this project has repeatedly been
bitten by; the norm is to refuse.

This is a static check because proving it dynamically costs a PyInstaller
build and a twenty-run performance measurement per combination.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

SCRIPTS = Path("scripts")

_PARAM_SWITCH = re.compile(r"\[switch\]\$(\w+)")
# Top-level only: a block opening in column 0. Nested `if ($WorkingDirectory)`
# inside a helper function is indented and is not a gate section.
_TOP_LEVEL_IF = re.compile(r"^if \(\$(\w+)\)", re.MULTILINE)


def _gate_scripts() -> list[Path]:
    found = sorted(SCRIPTS.glob("check_phase*.ps1"))
    assert found, "no gate scripts found; the guard would pass vacuously"
    return found


def _block_end(lines: list[str], start: int) -> int:
    """Index of the closing brace in column 0 that ends a top-level block."""
    for index in range(start + 1, len(lines)):
        if lines[index].startswith("}"):
            return index
    return len(lines) - 1


def _conflicts(text: str) -> list[tuple[str, str]]:
    """Pairs of (early-exit flag, later work flag) the script cannot honour."""
    lines = text.splitlines()
    switches = set(_PARAM_SWITCH.findall(text))

    blocks: list[tuple[str, int, int]] = []
    for index, line in enumerate(lines):
        match = _TOP_LEVEL_IF.match(line)
        if match and match.group(1) in switches:
            blocks.append((match.group(1), index, _block_end(lines, index)))

    exits = [
        (flag, start)
        for flag, start, end in blocks
        if any("exit 0" in line for line in lines[start : end + 1])
    ]

    # A `Skip*` flag asks for *less* work, so an early exit cancelling it costs
    # nothing and is not a hazard. Only a flag that requests work can be
    # silently denied. This is a naming convention rather than a proof, and it
    # is the convention every gate script here follows.
    return sorted(
        {
            (exit_flag, work_flag)
            for exit_flag, exit_line in exits
            for work_flag, work_start, _ in blocks
            if work_flag != exit_flag
            and work_start > exit_line
            and not work_flag.startswith("Skip")
        }
    )


def _refuses(text: str, exit_flag: str, work_flag: str) -> bool:
    """Whether the script rejects `-exit_flag -work_flag` before doing work.

    Deliberately shape-agnostic: any line mentioning both flags together with
    a `throw` nearby counts. Pinning an exact spelling would make the guard
    fail on a rewording that is still correct.
    """
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if f"${exit_flag}" in line and f"${work_flag}" in line:
            window = "\n".join(lines[index : index + 6])
            if "throw" in window:
                return True
    return False


@pytest.mark.parametrize("script", _gate_scripts(), ids=lambda p: p.name)
def test_no_flag_silently_cancels_another_flags_work(script: Path) -> None:
    text = script.read_text(encoding="utf-8")

    unrefused = [
        f"-{exit_flag} -{work_flag}"
        for exit_flag, work_flag in _conflicts(text)
        if not _refuses(text, exit_flag, work_flag)
    ]

    assert not unrefused, (
        f"{script.name} accepts {unrefused} but exits before that work runs, "
        "so it returns 0 having done less than it was asked. Refuse the "
        "combination up front instead of skipping quietly."
    )


def test_the_detector_finds_a_conflict_it_should(tmp_path: Path) -> None:
    """The guard above passes once the scripts are fixed, so pin the detector.

    Without this, deleting the body of `_conflicts` would leave every gate
    script 'passing' and nothing would notice.
    """
    script = "\n".join(
        [
            "param(",
            "    [switch]$SkipWeb,",
            "    [switch]$Perf",
            ")",
            "",
            "if ($SkipWeb) {",
            "    exit 0",
            "}",
            "",
            "if ($Perf) {",
            '    Write-Output "measuring"',
            "}",
            "",
        ]
    )

    assert _conflicts(script) == [("SkipWeb", "Perf")]
    assert not _refuses(script, "SkipWeb", "Perf")

"""A PowerShell script is never invoked with array splatting.

PowerShell has two splatting forms and they do different things. Splatting a
**hashtable** passes *named* parameters. Splatting an **array** passes
*positional* arguments -- and a `[switch]` parameter is never positional, so an
array splat into a switch-only script fails to bind every argument with
``PositionalParameterNotFound``.

`check_phase7.ps1` did exactly that. Its packaging step built an array so that
`-SemanticLocal` and `-SkipZip` could be added conditionally, then splatted it
into `build_package.ps1`, whose parameters are all switches. **The `-Package`
path could never have run**, and nothing noticed because that path is slow and
optional and therefore rarely exercised -- `documentation/memory.md` had already
recorded that `check_phase7.ps1` "is the one that goes unrun".

`check_phase6.ps1` passes the same switch literally and works, which is what
makes this a regression rather than a latent flaw in both.

The confusable case, deliberately allowed: `Invoke-Checked` array-splats into
`uv`. Splatting an array into a **native executable** is correct -- the elements
become raw argv strings and no parameter binder is involved. So the rule is not
"never array-splat", it is "never array-splat into a PowerShell script".
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

SCRIPTS = Path("scripts")

# `& (Join-Path ...) @name` or `& $path @name` -- an ampersand call whose target
# ends in .ps1 (or is built by Join-Path from a .ps1 literal) followed by an
# array-splatted variable.
_SPLAT_CALL = re.compile(
    r"&\s*(?P<target>\([^)]*\.ps1[^)]*\)|\$\w+)\s+@(?P<var>\w+)",
    re.IGNORECASE,
)


def _powershell_scripts() -> list[Path]:
    found = sorted(SCRIPTS.glob("*.ps1"))
    assert found, "no PowerShell scripts found; the guard would pass vacuously"
    return found


@pytest.mark.parametrize(
    "script", _powershell_scripts(), ids=lambda p: p.name
)
def test_no_powershell_script_is_called_with_array_splatting(
    script: Path,
) -> None:
    """Catch the binding failure statically, because running it is expensive.

    Proving this dynamically means a full PyInstaller build per gate script.
    The static form runs in milliseconds and fails for the same reason.
    """
    text = script.read_text(encoding="utf-8")
    offenders = [
        match.group(0)
        for match in _SPLAT_CALL.finditer(text)
        # A hashtable splat is written the same way at the call site, so the
        # declaration is what distinguishes them. Only flag a variable that is
        # assigned an @( ... ) array literal somewhere in the file.
        if re.search(
            rf"\${match.group('var')}\s*=\s*@\(", text
        )
    ]

    assert not offenders, (
        f"{script.name} array-splats into a PowerShell script: {offenders}. "
        "Array splatting binds positionally and a [switch] is never "
        "positional, so every argument fails to bind. Use a hashtable splat "
        "(@{ Name = $true }) or pass the switches literally."
    )

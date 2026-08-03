"""`.env.example` is the only place these settings are discoverable.

A variable that exists in the code and not in the example file is invisible: a
fresh clone has no `.env`, and nothing else lists what may go in one. That is
how `CODEATLAS_EPHEMERAL` shipped undocumented — its constant lives in
`cli/main.py` rather than `settings/env_file.py`, so a reader checking the
obvious module would not have found it either.

This scans the whole package rather than one module, for exactly that reason.
"""

from __future__ import annotations

import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_SOURCE = _ROOT / "src" / "codeatlas"
_EXAMPLE = _ROOT / ".env.example"

_VARIABLE = re.compile(r'"(CODEATLAS_[A-Z0-9_]+)"')


def _declared_variables() -> set[str]:
    found: set[str] = set()
    for path in _SOURCE.rglob("*.py"):
        found.update(_VARIABLE.findall(path.read_text(encoding="utf-8")))
    return found


def _is_documented(name: str, example: str) -> bool:
    """Whether ``name`` appears in its own right, not inside a longer name.

    A plain substring test silently passes for every prefix: `CODEATLAS_EPHEMERAL`
    is contained in `CODEATLAS_EPHEMERAL_REPOSITORIES`, so a documented long name
    would vouch for an undocumented short one. `\\b` does the right thing here
    because `_` is a word character — the boundary only falls where the name
    actually ends.
    """
    return re.search(rf"\b{re.escape(name)}\b", example) is not None


def test_every_environment_variable_is_documented() -> None:
    example = _EXAMPLE.read_text(encoding="utf-8")
    undocumented = sorted(
        name for name in _declared_variables() if not _is_documented(name, example)
    )

    assert undocumented == [], (
        "These environment variables are read by the code but absent from "
        f".env.example, so nobody cloning the repository can discover them: "
        f"{undocumented}"
    )


def test_the_scan_finds_the_variables_it_is_supposed_to_guard() -> None:
    # Without this, a broken regex or a moved source tree would make the test
    # above pass by finding nothing at all.
    declared = _declared_variables()

    assert "CODEATLAS_EPHEMERAL" in declared
    assert "CODEATLAS_DB_PATH" in declared
    assert len(declared) >= 10


def test_a_prefix_of_a_documented_name_does_not_count_as_documented() -> None:
    # The first version of this suite passed while `CODEATLAS_EPHEMERAL` was
    # absent, because `CODEATLAS_EPHEMERAL_REPOSITORIES` contained it. Pinned so
    # the check cannot quietly regress to substring matching.
    example = "# CODEATLAS_EPHEMERAL_REPOSITORIES=C:\\one\n"

    assert _is_documented("CODEATLAS_EPHEMERAL_REPOSITORIES", example) is True
    assert _is_documented("CODEATLAS_EPHEMERAL", example) is False

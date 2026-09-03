"""The packaged build ships both executables, and verifies the one it cannot help.

**Until 2026-09-04 the artifact shipped only `codeatlas.exe`.** `packaging/entry.py`
froze exactly one entry point, so an agent using the packaged Windows release --
the one the README tells people to unzip and run with no install -- **could not
use MCP at all**. It was source-checkout-only, and nothing said so: the README
listed the 22 tools without mentioning that the release does not contain them.

That is this project's recurring shape. `AGENTS.md` §2 names a coding agent as
one of three users and §13 requires MCP to wrap the same use cases as the CLI;
the CLI shipped and the MCP server did not.

Two properties are pinned here, both static, because proving them dynamically
costs a PyInstaller build:

1. **Both entry points are declared**, so a spec edit cannot quietly drop one.
2. **The build verifies the MCP executable by speaking the protocol to it.**
   This one matters more than it looks. `--help` cannot check a stdio server --
   it would block -- and `--help` is exactly what still worked on 2026-08-19
   while two missing data sets had otherwise destroyed the artifact, with
   `repo add` and `doctor` both dead. An existence check here would repeat a
   mistake the build script already carries a comment about.

**What this does NOT cover.** It does not build anything, so it cannot prove the
frozen executable works -- that is `tests/end_to_end/test_packaged_build.py`
behind `-Package`, and the build script's own verification step. A guard whose
scope is unstated gets mistaken for a guarantee.
"""

from __future__ import annotations

from pathlib import Path

import pytest

SPEC = Path("packaging/codeatlas.spec")
BUILD = Path("scripts/build_package.ps1")
VERIFIER = Path("scripts/verify_mcp_server.py")

ENTRY_POINTS = (
    ("packaging/entry.py", "codeatlas"),
    ("packaging/mcp_entry.py", "codeatlas-mcp"),
)


def _spec() -> str:
    return SPEC.read_text(encoding="utf-8")


def test_the_build_is_spec_driven() -> None:
    """Two executables in one bundle need a spec; args cannot express it.

    `pyinstaller a.py b.py` builds one program over two scripts, not two
    programs, so if the build ever goes back to a command line it has silently
    lost an executable.
    """
    assert SPEC.exists(), f"{SPEC} is missing; the build invokes it"
    assert "packaging/codeatlas.spec" in BUILD.read_text(encoding="utf-8"), (
        f"{BUILD} no longer builds from {SPEC}. A command-line invocation "
        "cannot produce two executables in one bundle."
    )


@pytest.mark.parametrize(("script", "executable"), ENTRY_POINTS)
def test_the_spec_declares_an_entry_point(script: str, executable: str) -> None:
    """Each entry point exists on disk and is named by the spec."""
    assert Path(script).exists(), f"{script} is missing"

    spec = _spec()
    assert Path(script).name in spec, (
        f"{SPEC} no longer references {script}, so the build would not produce "
        f"{executable}.exe"
    )
    assert f'name="{executable}"' in spec, (
        f"{SPEC} declares no EXE named {executable!r}. The packaged release "
        "would be missing it, and nothing else here would notice."
    )


def test_the_build_verifies_the_mcp_executable_by_protocol() -> None:
    """The MCP executable is exercised, not merely found on disk.

    A stdio server cannot answer `--help`, so the only honest check is the
    protocol. If this assertion fails because the build switched to an
    existence check, that is the 2026-08-19 lesson being unlearned.
    """
    assert VERIFIER.exists(), f"{VERIFIER} is missing; the build invokes it"

    build = BUILD.read_text(encoding="utf-8")
    assert "codeatlas-mcp.exe" in build, (
        f"{BUILD} does not look for codeatlas-mcp.exe"
    )
    assert "verify_mcp_server.py" in build, (
        f"{BUILD} no longer runs {VERIFIER}. Checking that the file exists is "
        "not checking that the server works -- `--help` was the one command "
        "that still worked on 2026-08-19."
    )


def test_the_verifier_requires_the_error_envelope() -> None:
    """The verification asserts a failure path, not only a success path.

    An agent meets errors more often than successes, and the envelope is the
    contract (`AGENTS.md` §12.6). A check that only proves `tools/list` works
    would pass against a server whose every failure crashed the client.
    """
    verifier = VERIFIER.read_text(encoding="utf-8")
    assert "REPOSITORY_NOT_FOUND" in verifier, (
        "the verifier no longer asserts that an unknown repository produces "
        "the error envelope"
    )
    assert "stdout_noise" in verifier, (
        "the verifier no longer checks for non-protocol output on stdout, "
        "which silently corrupts the JSON-RPC stream"
    )

"""Smoke tests against the packaged Windows build.

**Packaging changes no runtime contract.** A packaged build must answer exactly
what a source checkout answers; a difference is a defect, not a packaging
detail. These tests are how that claim is checked rather than asserted.

They run only when the artifact exists. Building it takes minutes, so
`check_phase6.ps1` builds it under `-Package` and skips these otherwise — the
skip is reported with its reason rather than passing silently, the same way the
Chromium gap is.
"""

from __future__ import annotations

import json
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
_ARTIFACT = _REPOSITORY_ROOT / "dist" / "codeatlas-win64" / "codeatlas.exe"

packaged = pytest.mark.skipif(
    not _ARTIFACT.is_file(),
    reason=(
        "no packaged build; run scripts/build_package.ps1 or"
        " check_phase6.ps1 -Package"
    ),
)


def _run(*arguments: str, timeout: float = 180.0) -> subprocess.CompletedProcess[str]:
    # Fixed argv, no shell: nothing here is interpolated from user input.
    return subprocess.run(
        [str(_ARTIFACT), *arguments],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


@packaged
def test_the_executable_runs_at_all() -> None:
    """The first thing to break in a frozen build: it does not start."""
    result = _run("--help")

    assert result.returncode == 0, result.stderr
    assert "repository intelligence" in result.stdout.lower()


@packaged
def test_the_packaged_build_migrates_a_fresh_database(tmp_path: Path) -> None:
    """Migrations are data files. `importlib.resources` finds them in a wheel;
    a frozen build has to have them bundled, and this is where that shows."""
    database = tmp_path / "db.sqlite"

    result = _run("repo", "list", "--db", str(database), "--json")

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == []
    assert database.exists()


@packaged
def test_the_packaged_build_indexes_and_answers(tmp_path: Path) -> None:
    """The whole vertical slice through a binary: register, index, resolve.

    This is what proves the tree-sitter native extensions were bundled and
    load — the failure mode a `--help` check would miss entirely.
    """
    database = tmp_path / "db.sqlite"
    source = tmp_path / "repo" / "src"
    source.mkdir(parents=True)
    (source / "service.py").write_text(
        "class PaymentService:\n"
        "    def capture(self, key: str) -> str:\n"
        "        return key\n",
        encoding="utf-8",
    )

    added = _run("repo", "add", str(tmp_path / "repo"), "--db", str(database), "--json")
    assert added.returncode == 0, added.stderr
    repository_id = json.loads(added.stdout)["repository_id"]

    indexed = _run("index", repository_id, "--db", str(database), "--json")
    assert indexed.returncode == 0, indexed.stderr

    found = _run(
        "symbol", repository_id, "PaymentService.capture", "--db", str(database),
        "--json",
    )
    assert found.returncode == 0, found.stderr
    payload = json.loads(found.stdout)
    assert payload["evidence"], "the packaged build resolved no evidence"
    assert payload["evidence"][0]["file_path"].endswith("service.py")


@packaged
def test_the_packaged_build_serves_the_web_application(tmp_path: Path) -> None:
    """The command the packaged build exists to run.

    Asserts both halves of the single-origin arrangement: the shell is served,
    and `/v1` on the same origin still answers as itself.
    """
    database = tmp_path / "db.sqlite"
    port = 8571
    server = subprocess.Popen(
        [
            str(_ARTIFACT), "serve", "--web",
            "--port", str(port),
            "--db", str(database),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        base = f"http://127.0.0.1:{port}"
        _wait_until_listening(server, f"{base}/v1/repositories")

        with urllib.request.urlopen(f"{base}/v1/repositories", timeout=10) as api:
            assert api.status == 200
            assert json.loads(api.read()) == []

        with urllib.request.urlopen(base, timeout=10) as shell:
            assert shell.status == 200
            assert "text/html" in shell.headers.get("content-type", "")

        # A client-side route must reach the shell rather than a 404.
        with urllib.request.urlopen(f"{base}/conversations/conv_x", timeout=10) as deep:
            assert deep.status == 200
    finally:
        server.terminate()
        server.wait(timeout=30)


def _wait_until_listening(
    server: subprocess.Popen[bytes], probe: str, *, timeout: float = 90.0
) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if server.poll() is not None:
            _, stderr = server.communicate()
            pytest.fail(
                f"the server exited before listening (code {server.returncode}):"
                f" {stderr.decode(errors='replace')}"
            )
        try:
            with urllib.request.urlopen(probe, timeout=2):
                return
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            time.sleep(0.2)
    pytest.fail("the packaged server never started listening")

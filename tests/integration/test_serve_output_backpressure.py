"""The server must keep answering when nobody reads its output.

A local server gets launched by things that are not terminals: a desktop
shortcut, a wrapper script, a task runner, a test harness. Several of those give
it a pipe for stdout and never read it. A pipe has a small fixed buffer — a few
kilobytes on Windows — and once it is full, `write` blocks *forever*.

That is how CodeAtlas deadlocked. uvicorn's access log writes one line per
request, synchronously, **on the event-loop thread**. After enough requests the
pipe filled, the write blocked, and the entire server stopped answering — not
the one request, all of them. It looked like a hang with no cause: the process
alive, memory and handles flat, no child processes, nothing in the log.

Found by the P6-08 performance measurement, which could not complete 20
change-analysis samples. The count where it died moved with how much had been
logged, not with how many requests had been made, which is the fingerprint of a
buffer rather than a leak.

The fix is that `serve` runs with uvicorn's access log off, so per-request
logging cannot block the loop — and, separately, so request paths are not
written anywhere by default (`CLAUDE.md` Section 17).
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from pathlib import Path

import pytest

# Comfortably more than a Windows pipe buffer holds in access-log lines. Before
# the fix this hung at roughly the fiftieth request; the margin is what keeps
# the test meaningful on a platform with a larger buffer.
_REQUESTS = 400
_PORT = 8641


@pytest.fixture()
def undrained_server(tmp_path: Path) -> Iterator[str]:
    """`serve`, with stdout and stderr piped and deliberately never read."""
    database = tmp_path / "db.sqlite"
    # Fixed argv, no shell. `-m` rather than the console script so the test
    # runs against this checkout without depending on an installed entry point.
    server = subprocess.Popen(
        [
            sys.executable, "-m", "codeatlas.cli.main", "serve",
            "--port", str(_PORT),
            "--db", str(database),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    base = f"http://127.0.0.1:{_PORT}"
    try:
        _wait_until_listening(server, f"{base}/v1/repositories")
        yield base
    finally:
        server.kill()
        server.wait(timeout=30)


def _wait_until_listening(
    server: subprocess.Popen[bytes], probe: str, *, timeout: float = 90.0
) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if server.poll() is not None:
            pytest.fail(f"the server exited before listening ({server.returncode})")
        try:
            with urllib.request.urlopen(probe, timeout=2):
                return
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            time.sleep(0.2)
    pytest.fail("the server never started listening")


def test_the_server_survives_an_unread_output_pipe(undrained_server: str) -> None:
    """Many requests, nobody reading the output, and it still answers.

    The assertion that matters is the *last* request, not the first. A blocked
    write does not fail early — everything works until the buffer fills.
    """
    for index in range(_REQUESTS):
        try:
            with urllib.request.urlopen(
                f"{undrained_server}/v1/repositories", timeout=15
            ) as response:
                assert response.status == 200
                assert json.loads(response.read()) == []
        except (TimeoutError, urllib.error.URLError) as error:
            pytest.fail(
                f"the server stopped answering at request {index + 1} of"
                f" {_REQUESTS}: {error!r}. Its output pipe is full and the"
                " event loop is blocked writing to it."
            )

"""Drive an MCP stdio server through a real handshake, and report what it did.

**Why this exists rather than a `--help` check.** On 2026-08-19 the packaged
build was destroyed by two missing data sets and `--help` was the one command
that still worked -- `repo add` and `doctor` both died. A smoke check that
avoids constructing services proves less than it looks. `codeatlas-mcp.exe`
cannot be checked with `--help` at all: it is a stdio server and would block.

So the check is the protocol itself: initialize, list tools, call one, and make
a call that must fail. That exercises the frozen bundle's data files, the
lazily-imported `mcp` transport, and the error envelope, which is every part of
this executable that packaging can break.

Used by `scripts/build_package.ps1` and by the packaged end-to-end suite, from
one implementation, so the build and the gate cannot check different things.

Usage::

    uv run python scripts/verify_mcp_server.py --db <path> -- <command> [args...]
    uv run python scripts/verify_mcp_server.py --db d.sqlite -- uv run codeatlas-mcp
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class Outcome:
    """What the server did, so a caller can assert rather than parse text."""

    server_name: str | None = None
    tool_count: int = 0
    tool_names: tuple[str, ...] = ()
    called_ok: bool = False
    error_code: str | None = None
    stdout_noise: list[str] = field(default_factory=list)
    failure: str | None = None


def _send(process: subprocess.Popen[bytes], message: dict[str, Any]) -> None:
    assert process.stdin is not None
    process.stdin.write(json.dumps(message).encode("utf-8") + b"\n")
    process.stdin.flush()


def _read(
    process: subprocess.Popen[bytes], noise: list[str], timeout: float
) -> dict[str, Any] | None:
    """Read one JSON-RPC message, recording anything else that arrives.

    Non-JSON on stdout is itself a defect and is collected rather than ignored:
    stdout is the protocol channel, and one stray line corrupts the stream for
    the client with no useful error.
    """
    assert process.stdout is not None
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        line = process.stdout.readline()
        if not line:
            return None
        text = line.decode("utf-8", errors="replace").strip()
        if not text:
            continue
        try:
            parsed: dict[str, Any] = json.loads(text)
            return parsed
        except json.JSONDecodeError:
            noise.append(text[:200])
    return None


def verify(command: list[str], database: Path, timeout: float = 60.0) -> Outcome:
    """Run the server and exercise it. Never raises; failures land in `Outcome`."""
    outcome = Outcome()
    environment = dict(os.environ)
    # Never the user's real database: `open_services` upgrades whatever it
    # opens, and a verification run must not migrate anything real.
    environment["CODEATLAS_DB_PATH"] = str(database)

    process = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=environment,
    )
    try:
        _send(process, {
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "codeatlas-verify", "version": "0"},
            },
        })
        initialized = _read(process, outcome.stdout_noise, timeout)
        if initialized is None:
            assert process.stderr is not None
            detail = process.stderr.read(4000).decode("utf-8", errors="replace")
            outcome.failure = f"no response to initialize; stderr: {detail[:1200]}"
            return outcome
        outcome.server_name = (
            initialized.get("result", {}).get("serverInfo", {}).get("name")
        )

        _send(process, {"jsonrpc": "2.0", "method": "notifications/initialized"})

        _send(process, {
            "jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {},
        })
        listing = _read(process, outcome.stdout_noise, timeout)
        if listing is None:
            outcome.failure = "no response to tools/list"
            return outcome
        tools = listing.get("result", {}).get("tools", [])
        outcome.tool_count = len(tools)
        outcome.tool_names = tuple(tool["name"] for tool in tools)

        _send(process, {
            "jsonrpc": "2.0", "id": 3, "method": "tools/call",
            "params": {"name": "list_repositories", "arguments": {}},
        })
        called = _read(process, outcome.stdout_noise, timeout)
        outcome.called_ok = bool(called and "result" in called)

        # A call that must fail, because an agent meets errors more often than
        # it meets successes and the envelope is the contract.
        _send(process, {
            "jsonrpc": "2.0", "id": 4, "method": "tools/call",
            "params": {
                "name": "get_status",
                "arguments": {"repository_id": "repo_does_not_exist"},
            },
        })
        failed = _read(process, outcome.stdout_noise, timeout)
        outcome.error_code = _error_code(failed)
        return outcome
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:  # pragma: no cover - defensive
            process.kill()


def _error_code(message: dict[str, Any] | None) -> str | None:
    """The envelope's `code`, dug out of the MCP text content."""
    if not message:
        return None
    contents = message.get("result", {}).get("content", [])
    for item in contents:
        try:
            payload = json.loads(item.get("text", ""))
        except (json.JSONDecodeError, AttributeError):
            continue
        code = payload.get("error", {}).get("code")
        if code:
            return str(code)
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True, type=Path)
    parser.add_argument("--expect-tools", type=int, default=None)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()

    command = [part for part in args.command if part != "--"]
    if not command:
        print("no server command given; pass it after --", file=sys.stderr)
        return 2

    outcome = verify(command, args.db)

    print(f"  server      : {outcome.server_name}")
    print(f"  tools       : {outcome.tool_count}")
    print(f"  tools/call  : {'ok' if outcome.called_ok else 'FAILED'}")
    print(f"  error code  : {outcome.error_code}")

    problems: list[str] = []
    if outcome.failure:
        problems.append(outcome.failure)
    if outcome.stdout_noise:
        problems.append(
            "non-protocol output on stdout, which corrupts the stream: "
            f"{outcome.stdout_noise[:3]}"
        )
    if not outcome.called_ok:
        problems.append("tools/call returned no result")
    if outcome.error_code != "REPOSITORY_NOT_FOUND":
        problems.append(
            "an unknown repository did not produce the REPOSITORY_NOT_FOUND "
            f"envelope; got {outcome.error_code!r}"
        )
    if args.expect_tools is not None and outcome.tool_count != args.expect_tools:
        problems.append(
            f"expected {args.expect_tools} tools, listed {outcome.tool_count}"
        )

    if problems:
        print("\nMCP verification FAILED:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1

    print("  MCP server verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

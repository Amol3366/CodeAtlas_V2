"""The security properties of the **packaged** build, checked on the binary.

Gate condition 8 asks for the security sweep "against the packaged artifact,
including the browser surface". The rest of `tests/security/` runs in process
against the source tree, which is the right place for parser limits, path
canonicalization, and FTS injection — none of those change when the code is
frozen.

What *can* change is everything about how the artifact is assembled and
launched: which interface it binds, what it ships, and how it serves files off
disk. That is what this file covers, by starting the real executable and
talking to it over a socket. A packaging defect lives precisely in the gap
between the source tree and the artifact, so testing the source tree twice
would not find one.

These run only when the artifact exists, and skip with their reason stated
otherwise — the same rule as `tests/end_to_end/test_packaged_build.py`.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterator
from pathlib import Path

import pytest

_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
_BUNDLE = _REPOSITORY_ROOT / "dist" / "codeatlas-win64"
_ARTIFACT = _BUNDLE / "codeatlas.exe"
_PORT = 8596

packaged = pytest.mark.skipif(
    not _ARTIFACT.is_file(),
    reason=(
        "no packaged build; run scripts/build_package.ps1 or"
        " check_phase6.ps1 -Package"
    ),
)


@pytest.fixture(scope="module")
def served(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    """The packaged build serving the API and the web application."""
    if not _ARTIFACT.is_file():
        pytest.skip("no packaged build")

    database = tmp_path_factory.mktemp("packaged-security") / "db.sqlite"
    # Fixed argv, no shell: nothing here comes from user input.
    server = subprocess.Popen(
        [
            str(_ARTIFACT), "serve", "--web",
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
                f"the packaged server exited before listening"
                f" ({server.returncode}): {stderr.decode(errors='replace')}"
            )
        try:
            with urllib.request.urlopen(probe, timeout=2):
                return
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            time.sleep(0.2)
    pytest.fail("the packaged server never started listening")


def _send(
    url: str,
    method: str = "GET",
    payload: dict[str, object] | None = None,
) -> tuple[int, dict[str, str], str]:
    """`_fetch` for the verbs the provider surface needs."""
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=body, method=method)
    if body is not None:
        request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return (
                response.status,
                dict(response.headers),
                response.read().decode("utf-8", errors="replace"),
            )
    except urllib.error.HTTPError as error:
        return (
            error.code,
            dict(error.headers),
            error.read().decode("utf-8", errors="replace"),
        )


def _fetch(url: str) -> tuple[int, dict[str, str], str]:
    try:
        with urllib.request.urlopen(url, timeout=10) as response:
            return (
                response.status,
                dict(response.headers),
                response.read().decode("utf-8", errors="replace"),
            )
    except urllib.error.HTTPError as error:
        return (
            error.code,
            dict(error.headers),
            error.read().decode("utf-8", errors="replace"),
        )


# --- what it binds --------------------------------------------------------


@packaged
def test_the_server_is_not_reachable_off_loopback(served: str) -> None:
    """Bound to 127.0.0.1, so a LAN address on this machine must not answer.

    This is the property that keeps an unauthenticated service private. It is
    asserted against a real socket rather than against a constant, because a
    constant proves what someone intended and a socket proves what happened.
    """
    assert served  # the loopback server is up

    lan_address = socket.gethostbyname(socket.gethostname())
    if lan_address.startswith("127."):
        pytest.skip("this machine resolves its hostname to loopback")

    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.settimeout(3)
    try:
        connected = probe.connect_ex((lan_address, _PORT))
    finally:
        probe.close()

    assert connected != 0, (
        f"the packaged server answered on {lan_address}:{_PORT}; it must bind"
        " loopback only"
    )


@packaged
def test_binding_beyond_loopback_is_refused(tmp_path: Path) -> None:
    """The refusal must survive packaging, since the flag is how it would be
    lost — a default can be overridden, a refusal cannot."""
    result = subprocess.run(
        [
            str(_ARTIFACT), "serve",
            "--host", "0.0.0.0",
            "--port", str(_PORT + 1),
            "--db", str(tmp_path / "db.sqlite"),
        ],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )

    assert result.returncode != 0
    assert "loopback" in result.stderr.lower()


# --- what it sends --------------------------------------------------------


@packaged
def test_no_cors_headers_are_returned(served: str) -> None:
    """One origin is what lets the API register no CORS middleware. If a
    header appeared here, that reasoning would have quietly stopped holding."""
    _, headers, _ = _fetch(f"{served}/v1/repositories")

    lowered = {name.lower() for name in headers}
    assert not any(name.startswith("access-control-") for name in lowered)


@packaged
def test_an_error_response_carries_no_path_or_traceback(served: str) -> None:
    status, _, body = _fetch(f"{served}/v1/repositories/repo_does_not_exist")

    assert status == 404
    assert json.loads(body)["error"]["code"] == "REPOSITORY_NOT_FOUND"
    assert "Traceback" not in body
    assert "C:\\" not in body
    assert str(_BUNDLE) not in body


@packaged
def test_an_unknown_api_path_stays_json(served: str) -> None:
    """The SPA fallback must not swallow `/v1`. Returning HTML to a client
    expecting JSON turns a clear failure into a parse error further from the
    cause — and hides a typo'd path behind a 200."""
    status, headers, body = _fetch(f"{served}/v1/not-a-route")

    assert status == 404
    assert "application/json" in headers.get("content-type", "")
    assert "<!doctype html" not in body.lower()


# --- what it serves off disk ----------------------------------------------


@packaged
def test_traversal_out_of_the_asset_root_is_refused(served: str) -> None:
    """The static mount is the one route that takes a path from the URL."""
    for attempt in (
        "/../codeatlas.exe",
        "/..%2f..%2fcodeatlas.exe",
        "/assets/../../codeatlas.exe",
        "/....//codeatlas.exe",
    ):
        status, _, body = _fetch(f"{served}{attempt}")
        # A client-side route legitimately falls back to the shell, so the bar
        # is that the *executable* is never returned — not that the status is
        # a particular number.
        assert "MZ" not in body[:8], f"{attempt} served a binary"
        assert status in (200, 400, 404), f"{attempt} produced {status}"


# --- what it ships --------------------------------------------------------


@packaged
def test_the_bundle_ships_no_developer_material() -> None:
    """A packaged build is copied to other machines. Anything private that
    reaches it reaches them, and nothing here needs to be in a release."""
    forbidden = {
        ".env",
        ".git",
        "codeatlas.db",
        "uv.lock",
    }
    present = {entry.name for entry in _BUNDLE.rglob("*") if entry.name in forbidden}
    assert present == set(), f"the bundle ships {sorted(present)}"


@packaged
def test_the_bundle_ships_no_test_fixtures() -> None:
    """The evaluation corpus and the upgrade fixture contain deliberately
    hostile paths and a database with real repository content. They are test
    material, and a release has no use for them."""
    names = {entry.name for entry in _BUNDLE.rglob("*") if entry.is_file()}

    assert "schema_0008.db" not in names
    assert not any(name.endswith(".spec.ts") for name in names)


@packaged
def test_the_migrations_are_the_only_sql_that_ships() -> None:
    """A stray `.sql` in a release is either a migration or a mistake."""
    stray = [
        entry
        for entry in _BUNDLE.rglob("*.sql")
        if entry.parent.name != "migrations"
    ]

    assert stray == [], f"unexpected SQL in the bundle: {stray}"


# --- what it can be told to transmit --------------------------------------

# Phase 7 is the first phase in which the artifact can be configured to send
# repository content off the machine. `tests/contract/test_settings_api.py`
# proves the settings service withholds credentials and defaults to no
# provider; it proves that of the *source tree*, in process, with a
# `TestClient`. The properties that matter here are the ones a packaging
# defect could break without touching a line of that code: whether the routes
# survive freezing at all, and whether a frozen process that can read a
# credential from its environment can be made to hand it back.

# Shaped like the real thing, deliberately not usable. Nothing below asserts
# it works — only that a value the process can read never becomes a value the
# process returns.
_CREDENTIAL = "sk-packagedsurfacetest" + "0" * 32
_CREDENTIAL_PORT = 8597


@pytest.fixture(scope="module")
def provider_surface(
    tmp_path_factory: pytest.TempPathFactory,
) -> Iterator[tuple[str, str]]:
    """The packaged build with a credential in its environment and one
    repository registered. Yields the base URL and that repository's ID."""
    if not _ARTIFACT.is_file():
        pytest.skip("no packaged build")

    workspace = tmp_path_factory.mktemp("packaged-provider")
    repository = workspace / "repository"
    repository.mkdir()
    (repository / "example.py").write_text(
        "def add(left, right):\n    return left + right\n", encoding="utf-8"
    )

    environment = dict(os.environ)
    environment["OPENAI_API_KEY"] = _CREDENTIAL

    # Fixed argv, no shell: nothing here comes from user input.
    server = subprocess.Popen(
        [
            str(_ARTIFACT), "serve", "--web",
            "--port", str(_CREDENTIAL_PORT),
            "--db", str(workspace / "db.sqlite"),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=environment,
    )
    base = f"http://127.0.0.1:{_CREDENTIAL_PORT}"
    try:
        _wait_until_listening(server, f"{base}/v1/repositories")
        status, _, body = _send(
            f"{base}/v1/repositories", "POST", {"path": str(repository)}
        )
        assert status in (200, 201), f"registration failed ({status}): {body}"
        yield base, json.loads(body)["repository_id"]
    finally:
        server.terminate()
        server.wait(timeout=30)


@packaged
def test_the_packaged_build_exposes_the_provider_settings_surface(
    provider_surface: tuple[str, str],
) -> None:
    """If the settings router were dropped from the bundle, every privacy
    assertion below would pass vacuously by never being reachable."""
    base, repository_id = provider_surface
    query = urllib.parse.urlencode({"repository_id": repository_id})

    status, _, body = _send(f"{base}/v1/settings?{query}")

    assert status == 200, body
    assert json.loads(body)["repository_id"] == repository_id


@packaged
def test_a_freshly_registered_repository_transmits_nothing(
    provider_surface: tuple[str, str],
) -> None:
    """Default off, on the artifact. A build that shipped defaulting to a
    transmitting provider would send source off the machine of a user who
    never opted in — the single failure this phase most needs to not have."""
    base, repository_id = provider_surface
    query = urllib.parse.urlencode({"repository_id": repository_id})

    _, _, body = _send(f"{base}/v1/settings?{query}")
    settings = json.loads(body)

    assert settings["embedding_provider"] == "none"
    assert settings["transmits_off_machine"] is False


@packaged
def test_a_credential_in_the_environment_never_reaches_a_response(
    provider_surface: tuple[str, str],
) -> None:
    """The process can read it. No route may hand it back."""
    base, repository_id = provider_surface
    query = urllib.parse.urlencode({"repository_id": repository_id})

    responses = {
        "models": _send(f"{base}/v1/models"),
        "settings": _send(f"{base}/v1/settings?{query}"),
        "model test": _send(f"{base}/v1/models/test?{query}", "POST", {}),
        "diagnostics": _send(
            f"{base}/v1/repositories/{repository_id}/diagnostics"
        ),
    }

    for label, (status, _, body) in responses.items():
        # Asserted so this test cannot pass by never reaching the route. A
        # 404 with a short body satisfies "the credential is absent" while
        # proving nothing at all.
        assert status == 200, f"{label} answered {status}: {body}"
        assert _CREDENTIAL not in body, f"{label} returned the credential"
        # The tail alone would still be a usable secret.
        assert _CREDENTIAL[-16:] not in body, f"{label} leaked part of it"


@packaged
def test_an_unscoped_settings_call_is_refused(
    provider_surface: tuple[str, str],
) -> None:
    """Provider choice is per repository (ADR-0009). A call that names no
    repository has no default scope that would be safe to invent."""
    base, _ = provider_surface

    status, headers, body = _send(f"{base}/v1/settings")

    assert status == 422, body
    assert "application/json" in headers.get("content-type", "")
    assert "<!doctype html" not in body.lower()

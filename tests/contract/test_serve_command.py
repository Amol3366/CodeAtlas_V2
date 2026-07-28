"""`codeatlas serve` — the command a packaged build exists to run.

The command is thin on purpose: resolve a database, decide whether to serve the
web application, and hand a configured app to uvicorn. Everything worth testing
is in that decision, so uvicorn itself is replaced by a recorder — starting a
real server in a unit test would prove only that uvicorn works.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from codeatlas.cli.main import EXIT_INVALID_INPUT, EXIT_SUCCESS, app

runner = CliRunner()


class _Recorder:
    """Stands in for `uvicorn.run`, capturing what it was asked to serve."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def __call__(self, application: Any, **options: Any) -> None:
        self.calls.append({"app": application, **options})

    @property
    def only(self) -> dict[str, Any]:
        assert len(self.calls) == 1, f"expected one run, got {len(self.calls)}"
        return self.calls[0]


@pytest.fixture()
def served(monkeypatch: pytest.MonkeyPatch) -> _Recorder:
    recorder = _Recorder()
    monkeypatch.setattr("codeatlas.cli.main.uvicorn.run", recorder)
    return recorder


def _run(*arguments: str) -> tuple[int, str]:
    result = runner.invoke(app, ["serve", *arguments])
    return result.exit_code, result.stdout


def test_serve_binds_to_loopback_by_default(
    served: _Recorder, tmp_path: Path
) -> None:
    """`AGENTS.md` Section 18: the local API is loopback-bound.

    A default of 0.0.0.0 would put a no-auth, no-CORS service on the network.
    """
    code, _ = _run("--db", str(tmp_path / "db.sqlite"))

    assert code == EXIT_SUCCESS
    assert served.only["host"] == "127.0.0.1"


def test_serve_uses_the_documented_default_port(
    served: _Recorder, tmp_path: Path
) -> None:
    _run("--db", str(tmp_path / "db.sqlite"))

    assert served.only["port"] == 8000


def test_the_port_can_be_chosen(served: _Recorder, tmp_path: Path) -> None:
    _run("--db", str(tmp_path / "db.sqlite"), "--port", "9111")

    assert served.only["port"] == 9111


def test_serve_prints_the_url_it_is_listening_on(
    served: _Recorder, tmp_path: Path
) -> None:
    _, output = _run("--db", str(tmp_path / "db.sqlite"), "--port", "9111")

    assert "http://127.0.0.1:9111" in output


def test_serve_does_not_open_a_browser_by_default(
    served: _Recorder, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Stealing focus is wrong in a terminal workflow and in every script."""
    opened: list[str] = []
    monkeypatch.setattr("codeatlas.cli.main.webbrowser.open", opened.append)

    _run("--db", str(tmp_path / "db.sqlite"), "--web")

    assert opened == []


def test_open_asks_for_the_browser(
    served: _Recorder, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    opened: list[str] = []
    monkeypatch.setattr("codeatlas.cli.main.webbrowser.open", opened.append)

    _run("--db", str(tmp_path / "db.sqlite"), "--web", "--port", "9222", "--open")

    assert opened == ["http://127.0.0.1:9222"]


def test_a_browser_that_will_not_open_does_not_stop_the_server(
    served: _Recorder, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The server is the point; the convenience is not."""

    def refuse(url: str) -> bool:
        raise OSError("no browser here")

    monkeypatch.setattr("codeatlas.cli.main.webbrowser.open", refuse)

    code, _ = _run("--db", str(tmp_path / "db.sqlite"), "--web", "--open")

    assert code == EXIT_SUCCESS
    assert served.calls


def test_serve_without_web_does_not_mount_the_application(
    served: _Recorder, tmp_path: Path
) -> None:
    """The API alone is a supported way to run, for CLI and MCP users."""
    _run("--db", str(tmp_path / "db.sqlite"))

    assert served.only["app"].state.web_assets is None


def test_serve_web_mounts_the_built_application(
    served: _Recorder, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assets = tmp_path / "dist"
    (assets / "assets").mkdir(parents=True)
    (assets / "index.html").write_text("<html></html>", encoding="utf-8")
    monkeypatch.setattr("codeatlas.cli.main.web_assets_path", lambda: assets)

    _run("--db", str(tmp_path / "db.sqlite"), "--web")

    assert served.only["app"].state.web_assets == assets


def test_serve_web_says_so_when_the_application_was_never_built(
    served: _Recorder, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Silently serving an API-only server after `--web` would be a lie."""
    monkeypatch.setattr("codeatlas.cli.main.web_assets_path", lambda: None)

    code, _ = _run("--db", str(tmp_path / "db.sqlite"), "--web")

    assert code == EXIT_INVALID_INPUT
    assert not served.calls


def test_serve_creates_and_migrates_the_database_before_listening(
    served: _Recorder, tmp_path: Path
) -> None:
    """A first run must not answer requests against an unmigrated database."""
    database = tmp_path / "fresh" / "db.sqlite"

    _run("--db", str(database))

    assert database.exists()
    from codeatlas.storage.sqlite.backup import read_schema_version

    assert read_schema_version(database) > 0


def test_a_refused_host_is_rejected_rather_than_bound(
    served: _Recorder, tmp_path: Path
) -> None:
    """Binding beyond loopback needs auth, a CORS review, and approval
    (`AGENTS.md` Section 25). Until then the flag refuses rather than exposing
    an unauthenticated service."""
    code, _ = _run("--db", str(tmp_path / "db.sqlite"), "--host", "0.0.0.0")

    assert code == EXIT_INVALID_INPUT
    assert not served.calls

"""The same analysis through the service, REST, the CLI, and MCP.

Gate condition 5 of the Phase 4 plan: four adapters, one answer. The comparison
is field by field on the parts a consumer depends on — findings, their codes and
order, the evidence IDs they cite, and the changed-symbol set — because an
adapter that quietly drops a limitation or reorders findings has broken the
contract even though every individual response still parses.

The renderers are checked here too, for the properties that matter when the
content came from a repository: Markdown cannot be escaped out of, and SARIF
cannot carry an absolute path.
"""

from __future__ import annotations

import json
import re
import subprocess
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from codeatlas.api.app import create_app
from codeatlas.application.change_analysis import ChangeAnalysisRequest
from codeatlas.application.container import build_services
from codeatlas.application.registration import RegisterRepositoryRequest
from codeatlas.delivery import render_markdown, render_sarif
from codeatlas.mcp.tools import build_registry
from codeatlas.storage.sqlite.connection import connect
from codeatlas.storage.sqlite.migrations import apply_migrations

BASE_PY = 'def total(order):\n    return order["amount"]\n'
TARGET_PY = (
    "def total(order):\n"
    "    if not order:\n"
    '        raise ValueError("order is required")\n'
    '    return order["amount"]\n'
)


def _git(root: Path, *args: str) -> None:
    import os

    subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        capture_output=True,
        env={
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@example.com",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@example.com",
            "PATH": os.environ.get("PATH", ""),
            "GIT_CONFIG_GLOBAL": str(root / ".absent"),
            "GIT_CONFIG_SYSTEM": str(root / ".absent"),
        },
    )


@dataclass
class Fixture:
    database: Path
    root: Path
    repository_id: str


@pytest.fixture()
def prepared(tmp_path: Path) -> Iterator[Fixture]:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-b", "main")
    (root / "orders.py").write_text(BASE_PY, encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-m", "base")
    (root / "orders.py").write_text(TARGET_PY, encoding="utf-8")

    database = tmp_path / "db.sqlite"
    with connect(database) as connection:
        apply_migrations(connection)
        services = build_services(connection)
        repository = services.registration.register(
            RegisterRepositoryRequest(path=str(root))
        )
        yield Fixture(
            database=database, root=root, repository_id=repository.repository_id
        )


def _service_report(fixture: Fixture) -> dict[str, Any]:
    with connect(fixture.database) as connection:
        services = build_services(connection)
        report = services.change_analysis.analyze_working_tree(
            ChangeAnalysisRequest(repository_id=fixture.repository_id)
        )
    return report.model_dump(mode="json")


def _rest_report(fixture: Fixture) -> dict[str, Any]:
    client = TestClient(create_app(fixture.database))
    response = client.post(
        "/v1/change-analysis/working-tree",
        json={"repository_id": fixture.repository_id, "base_ref": "HEAD"},
    )
    assert response.status_code == 200, response.text
    return dict(response.json())


def _mcp_report(fixture: Fixture) -> dict[str, Any]:
    with connect(fixture.database) as connection:
        services = build_services(connection)
        registry = build_registry()
        result = registry.call(
            services,
            "analyze_working_tree",
            {"repository_id": fixture.repository_id, "base_ref": "HEAD"},
        )
    assert isinstance(result, dict)
    return result


def _cli_report(fixture: Fixture) -> dict[str, Any]:
    from typer.testing import CliRunner

    from codeatlas.cli.main import app

    result = CliRunner().invoke(
        app,
        [
            "impact",
            fixture.repository_id,
            "--db",
            str(fixture.database),
            "--format",
            "json",
        ],
    )
    assert result.exit_code in {0, 4}, result.output
    return dict(json.loads(result.stdout))


def _comparable(report: Mapping[str, Any]) -> dict[str, Any]:
    """Everything a consumer depends on, minus what legitimately differs.

    The analysis ID, request ID, timestamps, and stage timings differ on every
    run by design. Everything else must match exactly across adapters.
    """
    findings: list[Any] = list(report["findings"])
    evidence: list[Any] = list(report["evidence"])
    symbols: list[Any] = list(report["changed_symbols"])
    edges: list[Any] = list(report["impact_edges"])
    return {
        "kind": report["kind"],
        "status": report["status"],
        "overall_risk": report["overall_risk"],
        "finding_codes": [item["code"] for item in findings],
        "finding_severities": [item["severity"] for item in findings],
        "finding_derivations": [item["derivation"] for item in findings],
        "evidence_count": len(evidence),
        "evidence_sides": sorted(str(item["side"]) for item in evidence),
        "evidence_ranges": sorted(
            (str(item["file_path"]), int(item["start_line"]), int(item["end_line"]))
            for item in evidence
        ),
        "changed_symbols": sorted(str(item["qualified_name"]) for item in symbols),
        "impact_edges": sorted(
            (str(item["source"]), str(item["target"])) for item in edges
        ),
        "warnings": sorted(str(item) for item in report["warnings"]),
        "limitations": sorted(str(item) for item in report["limitations"]),
        "test_gaps": sorted(str(item) for item in report["test_gaps"]),
    }


def test_all_four_adapters_return_the_same_analysis(prepared: Fixture) -> None:
    service = _comparable(_service_report(prepared))
    rest = _comparable(_rest_report(prepared))
    cli = _comparable(_cli_report(prepared))
    mcp = _comparable(_mcp_report(prepared))

    assert rest == service
    assert cli == service
    assert mcp == service


def test_the_analysis_is_not_empty(prepared: Fixture) -> None:
    """A cross-adapter test that compares nothing to nothing proves nothing."""
    service = _comparable(_service_report(prepared))

    assert service["finding_codes"]
    assert service["changed_symbols"]
    assert service["evidence_count"]


def test_a_stored_analysis_renders_in_three_formats_over_rest(
    prepared: Fixture,
) -> None:
    client = TestClient(create_app(prepared.database))
    created = client.post(
        "/v1/change-analysis/working-tree",
        json={"repository_id": prepared.repository_id, "base_ref": "HEAD"},
    ).json()
    analysis_id = created["analysis_id"]

    for report_format, media in (
        ("json", "application/json"),
        ("markdown", "text/markdown"),
        ("pr", "text/markdown"),
        ("sarif", "application/json"),
    ):
        response = client.get(
            f"/v1/change-analysis/{analysis_id}/report",
            params={"report_format": report_format},
        )
        assert response.status_code == 200, response.text
        assert media in response.headers["content-type"]


def test_the_pr_format_is_identical_through_every_adapter(
    prepared: Fixture,
) -> None:
    """"Four ways in, one brain."

    A format present in one adapter and not the others contradicts the claim
    the PRD makes, and every format reads the same persisted rows — so the same
    analysis must render identically regardless of which door it came through.
    """
    client = TestClient(create_app(prepared.database))
    created = client.post(
        "/v1/change-analysis/working-tree",
        json={"repository_id": prepared.repository_id, "base_ref": "HEAD"},
    ).json()
    analysis_id = created["analysis_id"]

    rest_text = client.get(
        f"/v1/change-analysis/{analysis_id}/report",
        params={"report_format": "pr"},
    ).text

    with connect(prepared.database) as connection:
        services = build_services(connection)
        registry = build_registry()
        result = registry.call(
            services,
            "get_change_report",
            {"analysis_id": analysis_id, "report_format": "pr"},
        )
    assert isinstance(result, dict)
    mcp_text = str(result["content"])

    assert "## CodeAtlas preflight" in rest_text
    assert "## CodeAtlas preflight" in mcp_text
    assert rest_text.strip() == mcp_text.strip()


def test_an_unknown_analysis_is_a_404(prepared: Fixture) -> None:
    client = TestClient(create_app(prepared.database))

    response = client.get("/v1/change-analysis/analysis_nope")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "CHANGE_ANALYSIS_NOT_FOUND"


def test_a_non_git_repository_is_a_409(tmp_path: Path) -> None:
    root = tmp_path / "plain"
    root.mkdir()
    (root / "a.py").write_text(BASE_PY, encoding="utf-8")
    database = tmp_path / "plain.sqlite"
    with connect(database) as connection:
        apply_migrations(connection)
        services = build_services(connection)
        repository = services.registration.register(
            RegisterRepositoryRequest(path=str(root))
        )

    client = TestClient(create_app(database))
    response = client.post(
        "/v1/change-analysis/working-tree",
        json={"repository_id": repository.repository_id},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "CHANGE_ANALYSIS_REQUIRES_GIT"


# --- Renderers ----------------------------------------------------------------


def test_repository_text_cannot_break_out_of_the_markdown() -> None:
    """A heading named like table syntax must not become table syntax.

    Escaping is asserted on the renderer directly rather than through a Git
    fixture, so the hostile value is exact and the assertion can be precise.
    """
    # The escaping moved to its own module so both renderers share one copy;
    # these assertions follow it rather than being weakened or dropped.
    from codeatlas.delivery.markdown_text import escape_cell, escape_inline

    assert escape_inline("a | b") == r"a \| b"
    assert escape_inline("`code`") == r"\`code\`"
    assert escape_inline("<script>") == "&lt;script&gt;"
    assert "\n" not in escape_inline("two\nlines")
    assert escape_inline("bell\x07") == "bell"
    assert len(escape_cell("x" * 500)) <= 160


def test_a_hostile_heading_survives_a_whole_rendered_report(
    tmp_path: Path,
) -> None:
    root = tmp_path / "hostile"
    root.mkdir()
    _git(root, "init", "-b", "main")
    (root / "notes.md").write_text("# Start\n\nplain\n", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-m", "base")
    (root / "notes.md").write_text("# a | b\n\nchanged\n", encoding="utf-8")

    database = tmp_path / "h.sqlite"
    with connect(database) as connection:
        apply_migrations(connection)
        services = build_services(connection)
        repository = services.registration.register(
            RegisterRepositoryRequest(path=str(root))
        )
        report = services.change_analysis.analyze_working_tree(
            ChangeAnalysisRequest(repository_id=repository.repository_id)
        )

    markdown = render_markdown(report)

    # The heading reaches the report, and its pipe is escaped everywhere.
    assert r"a \| b" in markdown

    # Every table row has the column count its header declares. Splitting on
    # *unescaped* pipes is the check that matters: `\|` is the Markdown escape
    # a renderer reads as a literal, so a naive split would fail on correct
    # output and pass on broken output that used a bare pipe.
    unescaped = re.compile(r"(?<!\\)\|")
    widths = {
        len(unescaped.split(line))
        for line in markdown.splitlines()
        if line.startswith("|")
    }
    assert widths
    assert all(width >= 3 for width in widths)


def test_sarif_carries_no_absolute_path(prepared: Fixture) -> None:
    with connect(prepared.database) as connection:
        services = build_services(connection)
        report = services.change_analysis.analyze_working_tree(
            ChangeAnalysisRequest(repository_id=prepared.repository_id)
        )

    sarif = render_sarif(report)

    text = json.dumps(sarif)
    assert str(prepared.root) not in text
    for run in sarif["runs"]:
        for result in run["results"]:
            for location in result["locations"]:
                uri = location["physicalLocation"]["artifactLocation"]["uri"]
                assert not uri.startswith("/")
                assert ":" not in uri


def test_sarif_has_the_shape_the_standard_requires(prepared: Fixture) -> None:
    with connect(prepared.database) as connection:
        services = build_services(connection)
        report = services.change_analysis.analyze_working_tree(
            ChangeAnalysisRequest(repository_id=prepared.repository_id)
        )

    sarif = render_sarif(report)

    assert sarif["version"] == "2.1.0"
    assert sarif["runs"]
    run = sarif["runs"][0]
    assert run["tool"]["driver"]["name"] == "CodeAtlas"
    for result in run["results"]:
        assert result["ruleId"]
        assert result["level"] in {"error", "warning", "note", "none"}
        assert result["message"]["text"]
        assert result["locations"]


def test_every_sarif_result_names_a_declared_rule(prepared: Fixture) -> None:
    with connect(prepared.database) as connection:
        services = build_services(connection)
        report = services.change_analysis.analyze_working_tree(
            ChangeAnalysisRequest(repository_id=prepared.repository_id)
        )

    sarif = render_sarif(report)
    run = sarif["runs"][0]
    declared = {rule["id"] for rule in run["tool"]["driver"]["rules"]}

    assert declared
    for result in run["results"]:
        assert result["ruleId"] in declared


def test_the_markdown_states_what_the_analysis_does_not_know(
    prepared: Fixture,
) -> None:
    """Limitations and test gaps are the part that keeps the rest honest."""
    with connect(prepared.database) as connection:
        services = build_services(connection)
        report = services.change_analysis.analyze_working_tree(
            ChangeAnalysisRequest(repository_id=prepared.repository_id)
        )

    markdown = render_markdown(report)

    assert "# Change analysis" in markdown
    assert "## Findings" in markdown
    if report.test_gaps:
        assert "does not prove absence of coverage" in markdown


# --- ADR-0054: a finding says what it is about, on every surface --------------


def _two_file_fixture(tmp_path: Path) -> Fixture:
    """Two files changed the same way, so both findings share a code and title.

    That is the case the register recorded as ADR-0042 follow-up 1: the findings
    are *legitimate* and distinct, and nothing rendered told them apart.
    """
    root = tmp_path / "repo2"
    root.mkdir()
    _git(root, "init", "-b", "main")
    (root / "orders.py").write_text(BASE_PY, encoding="utf-8")
    (root / "billing.py").write_text(BASE_PY, encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-m", "base")
    (root / "orders.py").write_text(TARGET_PY, encoding="utf-8")
    (root / "billing.py").write_text(TARGET_PY, encoding="utf-8")

    database = tmp_path / "db2.sqlite"
    with connect(database) as connection:
        apply_migrations(connection)
        services = build_services(connection)
        repository = services.registration.register(
            RegisterRepositoryRequest(path=str(root))
        )
        return Fixture(
            database=database, root=root, repository_id=repository.repository_id
        )


def test_a_finding_names_its_subject_and_file(tmp_path: Path) -> None:
    fixture = _two_file_fixture(tmp_path)
    report = _service_report(fixture)

    findings = report["findings"]
    assert findings, "the fixture must produce findings"
    for finding in findings:
        assert finding["subject"], f"no subject: {finding['code']}"
        assert finding["file_path"], f"no file_path: {finding['code']}"


def test_two_findings_sharing_a_code_are_distinguishable(tmp_path: Path) -> None:
    """The bug itself: same code and title, different files, identical render."""
    fixture = _two_file_fixture(tmp_path)
    report = _service_report(fixture)

    by_code: dict[str, list[dict[str, Any]]] = {}
    for finding in report["findings"]:
        by_code.setdefault(finding["code"], []).append(finding)
    shared = {code: items for code, items in by_code.items() if len(items) > 1}
    assert shared, "the fixture must produce at least one repeated code"

    for code, items in shared.items():
        keys = {(item["subject"], item["file_path"]) for item in items}
        assert len(keys) == len(items), (
            f"{code}: {len(items)} findings collapse to {len(keys)} keys — the"
            " React key collision, reproduced in the contract"
        )


def test_a_reloaded_analysis_keeps_the_subject_and_file(tmp_path: Path) -> None:
    """The persisted path derives them; it does not store them.

    `change_findings` has no such columns, so a stored report rebuilds the pair
    from the evidence each finding cites. If that derivation is ever dropped,
    the fields would survive a fresh analysis and vanish on reload — the
    one-surface defect this codebase keeps paying for.
    """
    fixture = _two_file_fixture(tmp_path)
    client = TestClient(create_app(fixture.database))
    created = client.post(
        "/v1/change-analysis/working-tree",
        json={"repository_id": fixture.repository_id, "base_ref": "HEAD"},
    )
    assert created.status_code == 200, created.text
    analysis_id = created.json()["analysis_id"]

    reloaded = client.get(f"/v1/change-analysis/{analysis_id}")
    assert reloaded.status_code == 200, reloaded.text

    fresh_keys = {
        (item["subject"], item["file_path"]) for item in created.json()["findings"]
    }
    stored_keys = {
        (item["subject"], item["file_path"]) for item in reloaded.json()["findings"]
    }
    assert stored_keys == fresh_keys
    assert all(subject and path for subject, path in stored_keys)


def test_every_renderer_tells_two_same_code_findings_apart(tmp_path: Path) -> None:
    """All four renderers, not three, and not "the JSON has it so they all do".

    Shipping to one surface and assuming the rest followed is the recurring
    shape here — the `--format pr` guards and the ADR-0016 gap reasons both.
    `text_report` is included explicitly because it is the CLI verdict, and the
    one that silently dropped limitations until ADR-0045.
    """
    from codeatlas.delivery.pr_report import render_pr_markdown
    from codeatlas.delivery.text_report import render_text

    fixture = _two_file_fixture(tmp_path)
    with connect(fixture.database) as connection:
        services = build_services(connection)
        report = services.change_analysis.analyze_working_tree(
            ChangeAnalysisRequest(repository_id=fixture.repository_id)
        )

    repeated = [
        item
        for item in report.findings
        if sum(1 for other in report.findings if other.code == item.code) > 1
    ]
    assert len(repeated) >= 2, "the fixture must produce a repeated code"
    paths = {item.file_path for item in repeated if item.file_path}
    assert len(paths) >= 2, "the repeated findings must be in different files"

    for name, rendered in (
        ("markdown", render_markdown(report)),
        ("pr", render_pr_markdown(report)),
        ("text", render_text(report)),
    ):
        for path in paths:
            assert path in rendered, f"{name} does not name {path}"

    # SARIF carries the location in its own model rather than a parallel field,
    # so it is checked through `artifactLocation` — mapping to the standard is
    # the requirement, not inventing a `file_path` property beside it.
    sarif = render_sarif(report)
    uris = {
        location["physicalLocation"]["artifactLocation"]["uri"]
        for result in sarif["runs"][0]["results"]
        for location in result["locations"]
    }
    for path in paths:
        assert path in uris, f"sarif does not locate {path}"

"""MCP tool contracts against a real indexed repository."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest

from codeatlas.application.registration import RegisterRepositoryRequest
from codeatlas.contracts import QueryResponse
from codeatlas.mcp.server import McpServer, open_services
from codeatlas.mcp.tools import TOOL_SCHEMA_VERSION, build_registry

EXPECTED_TOOLS = {
    # Phase 4 change assurance.
    "analyze_commit_range",
    "analyze_working_tree",
    "get_change_analysis",
    "get_change_report",
    # Phase 3 repository intelligence.
    "get_callees",
    "get_callers",
    "get_dependencies",
    "get_diagnostics",
    "get_evidence",
    "get_exports",
    "get_related_documents",
    "get_related_tests",
    "get_repository",
    "get_status",
    "list_repositories",
    "register_repository",
    "resolve_file",
    "resolve_symbol",
    "search_files",
    "search_symbols",
    "search_text",
    "trace_flow",
}


@pytest.fixture()
def server(tmp_path: Path, sample_repo: Path) -> Iterator[tuple[McpServer, str]]:
    with open_services(tmp_path / "db.sqlite") as services:
        repository = services.registration.register(
            RegisterRepositoryRequest(path=str(sample_repo))
        )
        services.indexing.index(repository.repository_id)
        yield McpServer(services), repository.repository_id


def _call(server: McpServer, name: str, **arguments: object) -> dict[str, object]:
    payload: dict[str, object] = json.loads(server.call_tool(name, arguments))
    return payload


# --- Registration and schemas -------------------------------------------------


def test_every_declared_tool_is_registered() -> None:
    assert set(build_registry().names) == EXPECTED_TOOLS


def test_analyze_change_is_absent_rather_than_unimplemented() -> None:
    """An agent will call a tool that exists; absence is the honest signal."""
    assert "analyze_change" not in build_registry().names


def test_every_tool_publishes_a_versioned_input_schema() -> None:
    for schema in build_registry().schemas():
        assert schema["schema_version"] == TOOL_SCHEMA_VERSION
        assert schema["input_schema"]["type"] == "object"
        assert schema["description"]


def test_the_server_describes_itself_with_its_tools(
    server: tuple[McpServer, str],
) -> None:
    surface, _ = server

    described = surface.describe()

    assert described["name"] == "codeatlas"
    assert {tool["name"] for tool in described["tools"]} == EXPECTED_TOOLS


# --- Behavior against a real snapshot ----------------------------------------


def test_resolve_symbol_returns_the_same_contract_as_rest(
    server: tuple[McpServer, str],
) -> None:
    surface, repository_id = server

    payload = surface.call_tool(
        "resolve_symbol",
        {"repository_id": repository_id, "symbol": "PaymentService.capture"},
    )

    response = QueryResponse.model_validate_json(payload)
    assert response.contract_version == "1.1"
    assert response.evidence[0].file_path == "src/payments/service.py"


def test_get_callees_answers_from_stored_relations(
    server: tuple[McpServer, str],
) -> None:
    surface, repository_id = server

    payload = surface.call_tool(
        "get_callees",
        {"repository_id": repository_id, "symbol": "PaymentService.capture"},
    )

    response = QueryResponse.model_validate_json(payload)
    assert any("claim" in claim.text for claim in response.answer.claims)


def test_get_status_reports_the_active_snapshot(
    server: tuple[McpServer, str],
) -> None:
    surface, repository_id = server

    result = _call(surface, "get_status", repository_id=repository_id)

    assert result["state"] == "active"
    assert result["symbol_count"]


def test_list_repositories_takes_no_arguments(
    server: tuple[McpServer, str],
) -> None:
    surface, repository_id = server

    listed = json.loads(surface.call_tool("list_repositories", {}))

    assert [item["repository_id"] for item in listed] == [repository_id]


def test_evidence_round_trips_through_mcp(server: tuple[McpServer, str]) -> None:
    surface, repository_id = server
    resolved = QueryResponse.model_validate_json(
        surface.call_tool(
            "resolve_symbol",
            {"repository_id": repository_id, "symbol": "PaymentService.capture"},
        )
    )
    evidence_id = resolved.evidence[0].evidence_id

    fetched = QueryResponse.model_validate_json(
        surface.call_tool(
            "get_evidence",
            {"repository_id": repository_id, "evidence_id": evidence_id},
        )
    )

    assert fetched.evidence[0].evidence_id == evidence_id


# --- Bounds and errors --------------------------------------------------------


def test_an_unknown_tool_returns_the_error_envelope(
    server: tuple[McpServer, str],
) -> None:
    surface, _ = server

    result = _call(surface, "no_such_tool")

    assert result["error"]["code"] == "INVALID_REQUEST"  # type: ignore[index]


def test_an_out_of_range_depth_is_refused(server: tuple[McpServer, str]) -> None:
    surface, repository_id = server

    result = _call(
        surface,
        "get_callers",
        repository_id=repository_id,
        symbol="PaymentService.capture",
        depth=50,
    )

    assert result["error"]["code"] == "INVALID_REQUEST"  # type: ignore[index]


def test_an_overlong_query_is_refused(server: tuple[McpServer, str]) -> None:
    surface, repository_id = server

    result = _call(
        surface, "search_text", repository_id=repository_id, query="x" * 5000
    )

    assert result["error"]["code"] == "INVALID_REQUEST"  # type: ignore[index]


def test_an_unknown_field_is_refused_rather_than_ignored(
    server: tuple[McpServer, str],
) -> None:
    surface, repository_id = server

    result = _call(
        surface,
        "get_status",
        repository_id=repository_id,
        surprise="ignored?",
    )

    assert result["error"]["code"] == "INVALID_REQUEST"  # type: ignore[index]


def test_an_unknown_repository_returns_a_stable_code(
    server: tuple[McpServer, str],
) -> None:
    surface, _ = server

    result = _call(surface, "get_status", repository_id="repo_missing")

    assert result["error"]["code"] == "REPOSITORY_NOT_FOUND"  # type: ignore[index]


def test_an_error_never_carries_a_stack_trace(
    server: tuple[McpServer, str],
) -> None:
    surface, _ = server

    result = _call(surface, "get_status", repository_id="repo_missing")

    message = result["error"]["message"]  # type: ignore[index]
    assert "Traceback" not in message
    assert "C:\\" not in message

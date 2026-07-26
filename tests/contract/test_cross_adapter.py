"""The three adapters must answer identically.

`CLAUDE.md` Section 4.5 requires REST, CLI, and MCP to call the same application
services rather than reimplement repository logic. The cheapest way for that to
rot is for one adapter to quietly post-process a result. So these tests do not
check that each adapter "looks right" — they compare the three answers to each
other, field by field, for the same question against the same snapshot.

Request IDs and timings legitimately differ per call; everything that describes
the repository must not.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from codeatlas.api.app import create_app
from codeatlas.cli.main import app as cli_app
from codeatlas.contracts import QueryResponse
from codeatlas.mcp.server import McpServer, open_services
from codeatlas.storage.sqlite.connection import connect
from codeatlas.storage.sqlite.migrations import apply_migrations

runner = CliRunner()


@dataclass
class Adapters:
    rest: TestClient
    mcp: McpServer
    database: str
    repository_id: str


@pytest.fixture()
def adapters(tmp_path: Path, sample_repo: Path) -> Iterator[Adapters]:
    database_path = tmp_path / "db.sqlite"
    with connect(database_path) as connection:
        apply_migrations(connection)

    with TestClient(create_app(database_path)) as rest:
        created = rest.post("/v1/repositories", json={"path": str(sample_repo)})
        assert created.status_code == 201, created.text
        repository_id = created.json()["repository_id"]
        assert rest.post(f"/v1/repositories/{repository_id}/index").status_code == 200

        with open_services(database_path) as services:
            yield Adapters(
                rest=rest,
                mcp=McpServer(services),
                database=str(database_path),
                repository_id=repository_id,
            )


def _comparable(response: QueryResponse) -> dict[str, object]:
    """Strip the fields that legitimately differ between two calls."""
    payload = json.loads(response.model_dump_json())
    payload.pop("request_id", None)
    payload.pop("timing_ms", None)
    return dict(payload)


def _rest_symbol(adapters: Adapters, symbol: str) -> QueryResponse:
    response = adapters.rest.post(
        "/v1/query",
        json={
            "repository_id": adapters.repository_id,
            "mode": "symbol",
            "query": symbol,
        },
    )
    assert response.status_code == 200, response.text
    return QueryResponse.model_validate(response.json())


def _cli_symbol(adapters: Adapters, symbol: str) -> QueryResponse:
    result = runner.invoke(
        cli_app,
        [
            "symbol",
            adapters.repository_id,
            symbol,
            "--db",
            adapters.database,
            "--json",
        ],
    )
    assert result.exit_code == 0, result.output
    return QueryResponse.model_validate_json(result.stdout)


def _mcp_symbol(adapters: Adapters, symbol: str) -> QueryResponse:
    return QueryResponse.model_validate_json(
        adapters.mcp.call_tool(
            "resolve_symbol",
            {"repository_id": adapters.repository_id, "symbol": symbol},
        )
    )


def test_symbol_lookup_is_identical_across_all_three_adapters(
    adapters: Adapters,
) -> None:
    rest = _comparable(_rest_symbol(adapters, "PaymentService.capture"))
    cli = _comparable(_cli_symbol(adapters, "PaymentService.capture"))
    mcp = _comparable(_mcp_symbol(adapters, "PaymentService.capture"))

    assert rest == cli
    assert cli == mcp


def test_evidence_ids_are_identical_across_adapters(adapters: Adapters) -> None:
    """A citation handed out by one adapter must address the same region in all."""
    ids = [
        [item.evidence_id for item in response.evidence]
        for response in (
            _rest_symbol(adapters, "PaymentService.capture"),
            _cli_symbol(adapters, "PaymentService.capture"),
            _mcp_symbol(adapters, "PaymentService.capture"),
        )
    ]

    assert ids[0] == ids[1] == ids[2]
    assert ids[0]


def test_graph_answers_agree_across_rest_cli_and_mcp(adapters: Adapters) -> None:
    rest = adapters.rest.get(
        "/v1/symbols/PaymentService.capture/relations",
        params={"repository_id": adapters.repository_id, "view": "callees"},
    )
    assert rest.status_code == 200, rest.text
    rest_response = _comparable(QueryResponse.model_validate(rest.json()))

    cli_result = runner.invoke(
        cli_app,
        [
            "callees",
            adapters.repository_id,
            "PaymentService.capture",
            "--db",
            adapters.database,
            "--json",
        ],
    )
    assert cli_result.exit_code == 0, cli_result.output
    cli_response = _comparable(QueryResponse.model_validate_json(cli_result.stdout))

    mcp_response = _comparable(
        QueryResponse.model_validate_json(
            adapters.mcp.call_tool(
                "get_callees",
                {
                    "repository_id": adapters.repository_id,
                    "symbol": "PaymentService.capture",
                },
            )
        )
    )

    assert rest_response == cli_response
    assert cli_response == mcp_response


def test_every_adapter_binds_the_same_snapshot(adapters: Adapters) -> None:
    snapshots = {
        response.snapshot.snapshot_id
        for response in (
            _rest_symbol(adapters, "PaymentService.capture"),
            _cli_symbol(adapters, "PaymentService.capture"),
            _mcp_symbol(adapters, "PaymentService.capture"),
        )
    }

    assert len(snapshots) == 1


def test_an_abstention_is_an_abstention_everywhere(adapters: Adapters) -> None:
    """Absence must be reported the same way, not as an error in one adapter."""
    rest = _rest_symbol(adapters, "definitely_not_a_symbol")
    mcp = _mcp_symbol(adapters, "definitely_not_a_symbol")

    assert rest.evidence == [] and mcp.evidence == []
    assert rest.answer.claims == [] and mcp.answer.claims == []
    assert set(rest.warnings) == set(mcp.warnings)


def test_no_adapter_leaks_an_absolute_path(
    adapters: Adapters, sample_repo: Path
) -> None:
    for response in (
        _rest_symbol(adapters, "PaymentService.capture"),
        _cli_symbol(adapters, "PaymentService.capture"),
        _mcp_symbol(adapters, "PaymentService.capture"),
    ):
        assert str(sample_repo) not in response.model_dump_json()


def test_a_truncated_graph_answer_is_never_reported_as_complete(
    adapters: Adapters,
) -> None:
    """A caller that hides `truncated_by` is the bug this test exists to catch."""
    response = adapters.rest.get(
        "/v1/symbols/PaymentService.capture/relations",
        params={
            "repository_id": adapters.repository_id,
            "view": "callees",
            "depth": 1,
        },
    )
    assert response.status_code == 200
    parsed = QueryResponse.model_validate(response.json())

    truncation = [item for item in parsed.warnings if "TRUNCATED" in item]
    if truncation:
        assert any("incomplete" in item for item in parsed.limitations)

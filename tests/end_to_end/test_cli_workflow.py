"""The CLI and the REST API must answer identically from the same services."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient
from typer.testing import CliRunner

from codeatlas.api.app import create_app
from codeatlas.cli.main import app as cli_app
from codeatlas.contracts import QueryResponse

runner = CliRunner()


def _database(tmp_path: Path) -> str:
    return str(tmp_path / "db.sqlite")


def _add(database: str, root: Path) -> str:
    result = runner.invoke(
        cli_app, ["repo", "add", str(root), "--db", database, "--json"]
    )
    assert result.exit_code == 0, result.output
    repository_id: str = json.loads(result.stdout)["repository_id"]
    return repository_id


def test_add_index_and_symbol_round_trip_in_json(
    sample_repo: Path, tmp_path: Path
) -> None:
    database = _database(tmp_path)
    repository_id = _add(database, sample_repo)

    indexed = runner.invoke(
        cli_app, ["index", repository_id, "--db", database, "--json"]
    )
    assert indexed.exit_code == 0, indexed.output
    assert json.loads(indexed.stdout)["state"] == "active"

    found = runner.invoke(
        cli_app,
        ["symbol", repository_id, "PaymentService.capture", "--db", database, "--json"],
    )
    assert found.exit_code == 0, found.output
    response = QueryResponse.model_validate_json(found.stdout)
    assert response.evidence[0].file_path == "src/payments/service.py"
    assert (response.evidence[0].start_line, response.evidence[0].end_line) == (7, 8)


def test_human_output_is_readable(sample_repo: Path, tmp_path: Path) -> None:
    database = _database(tmp_path)
    repository_id = _add(database, sample_repo)
    runner.invoke(cli_app, ["index", repository_id, "--db", database])

    result = runner.invoke(
        cli_app, ["symbol", repository_id, "PaymentService.capture", "--db", database]
    )
    assert result.exit_code == 0
    assert "src/payments/service.py" in result.stdout
    assert "7-8" in result.stdout


def test_repo_list_and_status(sample_repo: Path, tmp_path: Path) -> None:
    database = _database(tmp_path)
    repository_id = _add(database, sample_repo)
    runner.invoke(cli_app, ["index", repository_id, "--db", database])

    listed = runner.invoke(cli_app, ["repo", "list", "--db", database, "--json"])
    assert listed.exit_code == 0
    assert json.loads(listed.stdout)[0]["repository_id"] == repository_id

    status = runner.invoke(
        cli_app, ["status", repository_id, "--db", database, "--json"]
    )
    assert status.exit_code == 0
    body = json.loads(status.stdout)
    assert body["file_count"] == 3
    assert body["symbol_count"] > 0


def test_unknown_symbol_exits_with_the_partial_code(
    sample_repo: Path, tmp_path: Path
) -> None:
    database = _database(tmp_path)
    repository_id = _add(database, sample_repo)
    runner.invoke(cli_app, ["index", repository_id, "--db", database])

    result = runner.invoke(
        cli_app, ["symbol", repository_id, "NoSuchSymbol", "--db", database, "--json"]
    )
    assert result.exit_code == 4
    assert QueryResponse.model_validate_json(result.stdout).evidence == []


def test_unknown_repository_exits_with_the_unavailable_code(tmp_path: Path) -> None:
    result = runner.invoke(
        cli_app, ["status", "repo_missing", "--db", _database(tmp_path)]
    )
    assert result.exit_code == 3


def test_query_before_indexing_exits_with_the_unavailable_code(
    sample_repo: Path, tmp_path: Path
) -> None:
    database = _database(tmp_path)
    repository_id = _add(database, sample_repo)
    result = runner.invoke(
        cli_app, ["symbol", repository_id, "PaymentService", "--db", database]
    )
    assert result.exit_code == 3


def test_invalid_path_exits_with_the_policy_code(tmp_path: Path) -> None:
    result = runner.invoke(
        cli_app,
        ["repo", "add", str(tmp_path / "missing"), "--db", _database(tmp_path)],
    )
    assert result.exit_code == 5


def test_duplicate_registration_exits_with_the_invalid_input_code(
    sample_repo: Path, tmp_path: Path
) -> None:
    database = _database(tmp_path)
    _add(database, sample_repo)
    result = runner.invoke(cli_app, ["repo", "add", str(sample_repo), "--db", database])
    assert result.exit_code == 2


def test_empty_query_exits_with_the_invalid_input_code(
    sample_repo: Path, tmp_path: Path
) -> None:
    database = _database(tmp_path)
    repository_id = _add(database, sample_repo)
    runner.invoke(cli_app, ["index", repository_id, "--db", database])
    result = runner.invoke(cli_app, ["symbol", repository_id, "   ", "--db", database])
    assert result.exit_code == 2


def test_cli_and_rest_return_the_same_evidence_for_the_same_snapshot(
    sample_repo: Path, tmp_path: Path
) -> None:
    database_path = tmp_path / "db.sqlite"
    database = str(database_path)
    repository_id = _add(database, sample_repo)
    runner.invoke(cli_app, ["index", repository_id, "--db", database])

    cli_result = runner.invoke(
        cli_app,
        ["symbol", repository_id, "PaymentService.capture", "--db", database, "--json"],
    )
    assert cli_result.exit_code == 0
    cli_response = QueryResponse.model_validate_json(cli_result.stdout)

    with TestClient(create_app(database_path)) as client:
        rest = client.post(
            "/v1/query",
            json={
                "repository_id": repository_id,
                "query": "PaymentService.capture",
                "mode": "exact_symbol",
            },
        )
    assert rest.status_code == 200
    rest_response = QueryResponse.model_validate(rest.json())

    assert cli_response.snapshot.snapshot_id == rest_response.snapshot.snapshot_id
    cli_evidence = cli_response.evidence[0]
    rest_evidence = rest_response.evidence[0]
    assert (
        cli_evidence.file_path,
        cli_evidence.start_line,
        cli_evidence.end_line,
    ) == (
        rest_evidence.file_path,
        rest_evidence.start_line,
        rest_evidence.end_line,
    )
    assert cli_evidence.evidence_id == rest_evidence.evidence_id


def test_json_output_contains_no_absolute_paths(
    sample_repo: Path, tmp_path: Path
) -> None:
    database = _database(tmp_path)
    repository_id = _add(database, sample_repo)
    runner.invoke(cli_app, ["index", repository_id, "--db", database])
    result = runner.invoke(
        cli_app,
        ["symbol", repository_id, "PaymentService.capture", "--db", database, "--json"],
    )
    assert str(sample_repo) not in result.stdout


def test_search_returns_evidence_in_json(sample_repo: Path, tmp_path: Path) -> None:
    database = _database(tmp_path)
    repository_id = _add(database, sample_repo)
    runner.invoke(cli_app, ["index", repository_id, "--db", database])

    result = runner.invoke(
        cli_app,
        ["search", repository_id, "claim", "--db", database, "--json"],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["contract_version"] == "1.0"
    assert payload["evidence"]
    assert all(
        item["derivation"] == "high_confidence_heuristic"
        for item in payload["evidence"]
    )


def test_search_by_symbol_prefers_the_exact_match(
    sample_repo: Path, tmp_path: Path
) -> None:
    database = _database(tmp_path)
    repository_id = _add(database, sample_repo)
    runner.invoke(cli_app, ["index", repository_id, "--db", database])

    result = runner.invoke(
        cli_app,
        [
            "search",
            repository_id,
            "capture",
            "--kind",
            "symbols",
            "--db",
            database,
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["evidence"][0]["symbol"] == "PaymentService.capture"
    assert payload["evidence"][0]["derivation"] == "deterministic"


def test_an_unusable_search_query_exits_with_the_invalid_input_code(
    sample_repo: Path, tmp_path: Path
) -> None:
    database = _database(tmp_path)
    repository_id = _add(database, sample_repo)
    runner.invoke(cli_app, ["index", repository_id, "--db", database])

    result = runner.invoke(
        cli_app, ["search", repository_id, "***", "--db", database]
    )

    assert result.exit_code == 2
    assert "SEARCH_QUERY_INVALID" in result.output


def test_an_unknown_search_kind_is_rejected(
    sample_repo: Path, tmp_path: Path
) -> None:
    database = _database(tmp_path)
    repository_id = _add(database, sample_repo)

    result = runner.invoke(
        cli_app,
        ["search", repository_id, "claim", "--kind", "wat", "--db", database],
    )

    assert result.exit_code == 2


def test_a_search_with_no_match_exits_with_the_partial_code(
    sample_repo: Path, tmp_path: Path
) -> None:
    database = _database(tmp_path)
    repository_id = _add(database, sample_repo)
    runner.invoke(cli_app, ["index", repository_id, "--db", database])

    result = runner.invoke(
        cli_app, ["search", repository_id, "zzzznotpresent", "--db", database]
    )

    assert result.exit_code == 4
    assert "NO_LEXICAL_MATCH" in result.output


def test_rollback_without_a_target_exits_with_the_unavailable_code(
    sample_repo: Path, tmp_path: Path
) -> None:
    database = _database(tmp_path)
    repository_id = _add(database, sample_repo)
    runner.invoke(cli_app, ["index", repository_id, "--db", database])

    result = runner.invoke(cli_app, ["rollback", repository_id, "--db", database])

    assert result.exit_code == 3
    assert "NO_ROLLBACK_TARGET" in result.output


def test_search_output_contains_no_absolute_path(
    sample_repo: Path, tmp_path: Path
) -> None:
    database = _database(tmp_path)
    repository_id = _add(database, sample_repo)
    runner.invoke(cli_app, ["index", repository_id, "--db", database])

    result = runner.invoke(
        cli_app,
        ["search", repository_id, "claim", "--db", database, "--json"],
    )

    assert str(sample_repo) not in result.stdout
    assert str(sample_repo).replace("\\", "/") not in result.stdout


# --- Phase 3 graph, entity, and diagnostic commands ---------------------------


def _indexed(tmp_path: Path, sample_repo: Path) -> tuple[str, str]:
    database = _database(tmp_path)
    repository_id = _add(database, sample_repo)
    indexed = runner.invoke(cli_app, ["index", repository_id, "--db", database])
    assert indexed.exit_code == 0, indexed.output
    return database, repository_id


def test_callees_reports_a_resolved_call(sample_repo: Path, tmp_path: Path) -> None:
    database, repository_id = _indexed(tmp_path, sample_repo)

    result = runner.invoke(
        cli_app,
        [
            "callees",
            repository_id,
            "PaymentService.capture",
            "--db",
            database,
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    response = QueryResponse.model_validate_json(result.stdout)
    assert any("claim" in claim.text for claim in response.answer.claims)


def test_callers_of_an_uncalled_symbol_exits_partial(
    sample_repo: Path, tmp_path: Path
) -> None:
    """A script must be able to tell "no callers" from "found callers"."""
    database, repository_id = _indexed(tmp_path, sample_repo)

    result = runner.invoke(
        cli_app, ["callers", repository_id, "PaymentService.capture", "--db", database]
    )

    assert result.exit_code == 4


def test_deps_rejects_an_unknown_direction(
    sample_repo: Path, tmp_path: Path
) -> None:
    database, repository_id = _indexed(tmp_path, sample_repo)

    result = runner.invoke(
        cli_app,
        [
            "deps",
            repository_id,
            "src.payments.service",
            "--db",
            database,
            "--direction",
            "sideways",
        ],
    )

    assert result.exit_code == 2


def test_evidence_round_trips_from_a_symbol_lookup(
    sample_repo: Path, tmp_path: Path
) -> None:
    database, repository_id = _indexed(tmp_path, sample_repo)
    found = runner.invoke(
        cli_app,
        ["symbol", repository_id, "PaymentService.capture", "--db", database, "--json"],
    )
    looked_up = QueryResponse.model_validate_json(found.stdout)
    evidence_id = looked_up.evidence[0].evidence_id

    fetched = runner.invoke(
        cli_app, ["evidence", repository_id, evidence_id, "--db", database, "--json"]
    )

    assert fetched.exit_code == 0, fetched.output
    response = QueryResponse.model_validate_json(fetched.stdout)
    assert response.evidence[0].evidence_id == evidence_id


def test_an_unknown_evidence_id_exits_unavailable(
    sample_repo: Path, tmp_path: Path
) -> None:
    database, repository_id = _indexed(tmp_path, sample_repo)

    result = runner.invoke(
        cli_app, ["evidence", repository_id, "ev_missing", "--db", database]
    )

    assert result.exit_code == 3


def test_files_lists_the_active_snapshot(sample_repo: Path, tmp_path: Path) -> None:
    database, repository_id = _indexed(tmp_path, sample_repo)

    result = runner.invoke(
        cli_app, ["files", repository_id, "--db", database, "--json"]
    )

    assert result.exit_code == 0, result.output
    paths = {item["path"] for item in json.loads(result.stdout)}
    assert "src/payments/service.py" in paths


def test_diagnostics_reports_without_leaking_the_root(
    sample_repo: Path, tmp_path: Path
) -> None:
    database, repository_id = _indexed(tmp_path, sample_repo)

    result = runner.invoke(
        cli_app, ["diagnostics", repository_id, "--db", database, "--json"]
    )

    assert result.exit_code == 0, result.output
    assert str(sample_repo) not in result.stdout

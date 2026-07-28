from __future__ import annotations

import json
from pathlib import Path

from codeatlas.schema_export import (
    build_schema_bundle,
    schema_bundle_matches,
    write_schema_bundle,
)


def test_schema_bundle_contains_versioned_public_contracts() -> None:
    bundle = build_schema_bundle()

    assert bundle["contract_version"] == "1.1"
    assert set(bundle["schemas"]) == {
        "change_analysis_report",
        "conversation",
        "conversation_page",
        "error_envelope",
        "finding",
        "message",
        "message_evidence_item",
        "message_page",
        "message_run",
        "message_submission",
        "query_response",
        "stream_event",
        "stream_event_metadata",
    }
    query_schema = bundle["schemas"]["query_response"]
    assert query_schema["properties"]["contract_version"]["const"] == "1.1"
    assert query_schema["additionalProperties"] is False
    report_schema = bundle["schemas"]["change_analysis_report"]
    assert report_schema["properties"]["contract_version"]["const"] == "1.1"
    assert report_schema["additionalProperties"] is False
    # The web client generates its types from this bundle (ADR-0006 decision
    # 5), so every conversation schema must be strict for the generated types
    # to mean anything.
    for name in ("conversation", "message", "message_run", "stream_event"):
        assert bundle["schemas"][name]["additionalProperties"] is False
    event_schema = bundle["schemas"]["stream_event"]
    assert event_schema["properties"]["contract_version"]["const"] == "1.1"


def test_schema_export_is_stable_sorted_json(tmp_path: Path) -> None:
    output = tmp_path / "contract-v1.schema.json"

    write_schema_bundle(output)

    content = output.read_text(encoding="utf-8")
    assert content.endswith("\n")
    assert json.loads(content) == build_schema_bundle()
    assert content == json.dumps(
        build_schema_bundle(),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ) + "\n"


def test_schema_freshness_check_does_not_rewrite_stale_file(
    tmp_path: Path,
) -> None:
    output = tmp_path / "contract-v1.schema.json"
    write_schema_bundle(output)
    assert schema_bundle_matches(output)

    output.write_text("{}\n", encoding="utf-8")

    assert not schema_bundle_matches(output)
    assert output.read_text(encoding="utf-8") == "{}\n"

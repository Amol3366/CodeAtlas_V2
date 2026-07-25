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

    assert bundle["contract_version"] == "1.0"
    assert set(bundle["schemas"]) == {
        "error_envelope",
        "finding",
        "query_response",
        "stream_event_metadata",
    }
    query_schema = bundle["schemas"]["query_response"]
    assert query_schema["properties"]["contract_version"]["const"] == "1.0"
    assert query_schema["additionalProperties"] is False


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

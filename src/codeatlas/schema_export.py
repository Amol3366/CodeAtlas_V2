"""Deterministic JSON Schema export for public contract version 1.0."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from codeatlas.contracts import (
    CONTRACT_VERSION,
    ErrorEnvelope,
    Finding,
    QueryResponse,
    StreamEventMetadata,
)


def build_schema_bundle() -> dict[str, Any]:
    """Build the canonical schema bundle consumed by delivery adapters."""
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "contract_version": CONTRACT_VERSION,
        "schemas": {
            "error_envelope": ErrorEnvelope.model_json_schema(
                mode="serialization"
            ),
            "finding": Finding.model_json_schema(mode="serialization"),
            "query_response": QueryResponse.model_json_schema(
                mode="serialization"
            ),
            "stream_event_metadata": StreamEventMetadata.model_json_schema(
                mode="serialization"
            ),
        },
    }


def write_schema_bundle(output: Path) -> None:
    """Write the schema bundle with stable key ordering and UTF-8 encoding."""
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        _render_schema_bundle(), encoding="utf-8", newline="\n"
    )


def schema_bundle_matches(output: Path) -> bool:
    """Return whether a tracked schema is present and current without writing."""
    try:
        return output.read_text(encoding="utf-8") == _render_schema_bundle()
    except FileNotFoundError:
        return False


def _render_schema_bundle() -> str:
    rendered = json.dumps(
        build_schema_bundle(),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )
    return f"{rendered}\n"

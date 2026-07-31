"""Phase 7 packaged performance harness behavior."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.measure_phase7_perf import main


def test_phase7_perf_records_a_blocked_payload_when_artifact_is_missing(
    tmp_path: Path,
) -> None:
    output = tmp_path / "phase7-perf.json"

    exit_code = main(
        [
            "--artifact",
            str(tmp_path / "missing.exe"),
            "--json-output",
            str(output),
        ]
    )

    assert exit_code == 2
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["measurement_status"] == "blocked"
    assert payload["reason"] == "packaged_artifact_missing"
    assert payload["embedding_provider"] == "local"

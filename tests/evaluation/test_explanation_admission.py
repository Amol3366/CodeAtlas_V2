"""The P7-11 explanation admission artifact."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.run_phase7_explanation_ab import main


def test_explanation_ab_records_a_decline_against_the_semantic_baseline(
    tmp_path: Path,
) -> None:
    json_output = tmp_path / "explanation.json"
    markdown_output = tmp_path / "explanation.md"

    exit_code = main(
        [
            "--semantic-baseline",
            "docs/evaluation/baseline-phase-7.json",
            "--json-output",
            str(json_output),
            "--markdown-output",
            str(markdown_output),
        ]
    )

    assert exit_code == 0
    payload = json.loads(json_output.read_text(encoding="utf-8"))
    assert payload["admission"]["decision"] == "declined"
    assert {
        entry["delta"] for entry in payload["comparison"].values()
    } == {0.0}
    assert payload["citation_validation"]["citation_validity"] == 1.0
    assert "Admission decision: `declined`" in markdown_output.read_text(
        encoding="utf-8"
    )


def test_explanation_ab_check_accepts_fresh_artifacts(tmp_path: Path) -> None:
    json_output = tmp_path / "explanation.json"
    markdown_output = tmp_path / "explanation.md"
    args = [
        "--semantic-baseline",
        "docs/evaluation/baseline-phase-7.json",
        "--json-output",
        str(json_output),
        "--markdown-output",
        str(markdown_output),
    ]

    assert main(args) == 0
    assert main([*args, "--check"]) == 0

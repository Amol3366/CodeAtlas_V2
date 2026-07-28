"""Architecture rules: loading untrusted rule files, and reporting new edges only."""

from __future__ import annotations

from pathlib import Path

import pytest

from codeatlas.analysis.architecture import (
    RULES_RELATIVE_PATH,
    evaluate_rules,
    load_rules,
    parse_rules,
)
from codeatlas.analysis.impact import GraphSide
from codeatlas.contracts import Derivation, RelationKind, Severity, SymbolKind
from codeatlas.domain.errors import AnalysisRulesInvalidError
from codeatlas.domain.relations import RelationRecord, ResolutionState
from codeatlas.domain.symbols import SymbolRecord

VALID = """
[[rules]]
id = "controllers-cannot-access-repositories"
description = "Controllers must call services instead of repositories."
source_glob = "src/**/controllers/**"
forbidden_target_glob = "src/**/repositories/**"
relations = ["IMPORTS", "CALLS"]
severity = "high"
"""


def _write(tmp_path: Path, body: str) -> Path:
    path = tmp_path / RULES_RELATIVE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return tmp_path


def _symbol(name: str, file_id: str) -> SymbolRecord:
    return SymbolRecord(
        symbol_id=f"sym_{name}",
        symbol_version_id=f"symv_{name}",
        file_id=file_id,
        kind=SymbolKind.FUNCTION,
        name=name,
        qualified_name=name,
        module_path="",
        signature=None,
        start_line=1,
        end_line=2,
        start_byte=0,
        end_byte=1,
        content_hash=f"hash_{name}",
        visibility="public",
    )


def _relation(
    relation_id: str, source: str, target: str, kind: RelationKind
) -> RelationRecord:
    return RelationRecord(
        relation_id=relation_id,
        source_symbol_id=f"sym_{source}",
        target_symbol_id=f"sym_{target}",
        file_id="file_c",
        kind=kind,
        target_hint=target,
        resolution=ResolutionState.RESOLVED,
        derivation=Derivation.STATIC_RESOLVED,
        confidence=0.95,
        start_line=1,
        end_line=1,
        candidate_count=1,
    )


def _side(relations: tuple[RelationRecord, ...]) -> GraphSide:
    return GraphSide(
        symbols={
            "sym_create": _symbol("create", "file_c"),
            "sym_insert": _symbol("insert", "file_r"),
        },
        relations=relations,
        file_paths={
            "file_c": "src/app/controllers/order.py",
            "file_r": "src/app/repositories/order.py",
        },
    )


# --- Loading ------------------------------------------------------------------


def test_a_repository_without_a_rule_file_has_no_rules(tmp_path: Path) -> None:
    """Rules are opt-in; demanding a file would make them opt-out."""
    assert load_rules(tmp_path) == ()


def test_a_valid_rule_file_loads(tmp_path: Path) -> None:
    (rule,) = load_rules(_write(tmp_path, VALID))

    assert rule.rule_id == "controllers-cannot-access-repositories"
    assert rule.severity is Severity.HIGH
    assert RelationKind.CALLS in rule.relations


def test_malformed_toml_is_refused(tmp_path: Path) -> None:
    with pytest.raises(AnalysisRulesInvalidError):
        load_rules(_write(tmp_path, "[[rules]\nid = broken"))


def test_an_unknown_field_is_refused_rather_than_ignored() -> None:
    """A misspelled key would otherwise leave a rule silently doing nothing."""
    with pytest.raises(AnalysisRulesInvalidError):
        parse_rules(
            {
                "rules": [
                    {
                        "id": "r1",
                        "source_glob": "a/**",
                        "forbidden_target_glob": "b/**",
                        "sevrity": "high",
                    }
                ]
            }
        )


def test_an_unknown_relation_is_refused() -> None:
    with pytest.raises(AnalysisRulesInvalidError):
        parse_rules(
            {
                "rules": [
                    {
                        "id": "r1",
                        "source_glob": "a/**",
                        "forbidden_target_glob": "b/**",
                        "relations": ["TELEPORTS"],
                    }
                ]
            }
        )


def test_a_duplicate_rule_id_is_refused() -> None:
    entry = {
        "id": "r1",
        "source_glob": "a/**",
        "forbidden_target_glob": "b/**",
    }
    with pytest.raises(AnalysisRulesInvalidError):
        parse_rules({"rules": [entry, dict(entry)]})


def test_a_hostile_rule_id_is_refused() -> None:
    with pytest.raises(AnalysisRulesInvalidError):
        parse_rules(
            {
                "rules": [
                    {
                        "id": "../../etc/passwd",
                        "source_glob": "a/**",
                        "forbidden_target_glob": "b/**",
                    }
                ]
            }
        )


def test_too_many_rules_are_refused() -> None:
    entries = [
        {
            "id": f"r{index}",
            "source_glob": "a/**",
            "forbidden_target_glob": "b/**",
        }
        for index in range(201)
    ]
    with pytest.raises(AnalysisRulesInvalidError):
        parse_rules({"rules": entries})


def test_rules_must_be_an_array() -> None:
    with pytest.raises(AnalysisRulesInvalidError):
        parse_rules({"rules": "everything is forbidden"})


# --- Glob matching ------------------------------------------------------------


def test_a_double_star_glob_crosses_directory_levels(tmp_path: Path) -> None:
    rules = load_rules(_write(tmp_path, VALID))
    edge = _relation("rel_new", "create", "insert", RelationKind.CALLS)

    (violation,) = evaluate_rules(
        rules, base=_side(()), target=_side((edge,))
    )

    assert violation.rule_id == "controllers-cannot-access-repositories"
    assert violation.source == "create"
    assert violation.target == "insert"


def test_a_single_star_does_not_cross_a_separator() -> None:
    rules = parse_rules(
        {
            "rules": [
                {
                    "id": "r1",
                    "source_glob": "src/*.py",
                    "forbidden_target_glob": "src/**/repositories/**",
                }
            ]
        }
    )
    edge = _relation("rel_new", "create", "insert", RelationKind.CALLS)

    assert evaluate_rules(rules, base=_side(()), target=_side((edge,))) == ()


# --- New edges only -----------------------------------------------------------


def test_an_edge_already_present_in_the_base_is_not_reported(
    tmp_path: Path,
) -> None:
    """A repository adopting rules mid-life must not drown in old violations."""
    rules = load_rules(_write(tmp_path, VALID))
    edge = _relation("rel_old", "create", "insert", RelationKind.CALLS)

    assert evaluate_rules(rules, base=_side((edge,)), target=_side((edge,))) == ()


def test_a_relation_kind_outside_the_rule_is_not_reported(
    tmp_path: Path,
) -> None:
    rules = load_rules(_write(tmp_path, VALID))
    edge = _relation("rel_new", "create", "insert", RelationKind.DOCUMENTS)

    assert evaluate_rules(rules, base=_side(()), target=_side((edge,))) == ()


def test_an_unresolved_edge_cannot_violate_a_rule(tmp_path: Path) -> None:
    """A reference that reaches nothing has not crossed any boundary."""
    rules = load_rules(_write(tmp_path, VALID))
    edge = RelationRecord(
        relation_id="rel_new",
        source_symbol_id="sym_create",
        target_symbol_id=None,
        file_id="file_c",
        kind=RelationKind.CALLS,
        target_hint="insert",
        resolution=ResolutionState.UNRESOLVED,
        derivation=Derivation.HIGH_CONFIDENCE_HEURISTIC,
        confidence=0.7,
        start_line=1,
        end_line=1,
        candidate_count=0,
    )

    assert evaluate_rules(rules, base=_side(()), target=_side((edge,))) == ()


def test_no_rules_means_no_evaluation(tmp_path: Path) -> None:
    edge = _relation("rel_new", "create", "insert", RelationKind.CALLS)

    assert evaluate_rules((), base=_side(()), target=_side((edge,))) == ()


def test_a_symbol_whose_file_is_unknown_is_skipped() -> None:
    """Matching a glob against an opaque file ID would be nonsense."""
    rules = parse_rules(
        {
            "rules": [
                {
                    "id": "r1",
                    "source_glob": "**",
                    "forbidden_target_glob": "**",
                }
            ]
        }
    )
    edge = _relation("rel_new", "create", "insert", RelationKind.CALLS)
    side = GraphSide(
        symbols={
            "sym_create": _symbol("create", "file_c"),
            "sym_insert": _symbol("insert", "file_r"),
        },
        relations=(edge,),
        file_paths={},
    )

    assert evaluate_rules(rules, base=_side(()), target=side) == ()

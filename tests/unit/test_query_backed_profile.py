"""Contracts for query-backed language support (ADR-0065)."""

from __future__ import annotations

import dataclasses

from codeatlas.contracts import SymbolKind
from codeatlas.parsing.query_backed.profile import LanguageProfile


def test_profile_is_frozen_and_carries_its_capture_map() -> None:
    profile = LanguageProfile(
        language="java",
        grammar=object(),
        tags_query=object(),
        imports_query=object(),
        kind_by_capture={"definition.class": SymbolKind.CLASS},
        scope_node_types=frozenset({"class_declaration"}),
    )
    assert profile.language == "java"
    assert profile.kind_by_capture["definition.class"] is SymbolKind.CLASS
    assert dataclasses.is_dataclass(profile)
    try:
        profile.language = "go"  # type: ignore[misc]
    except dataclasses.FrozenInstanceError:
        return
    raise AssertionError("LanguageProfile must be frozen")

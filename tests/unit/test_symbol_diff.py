"""Unit tests for symbol-level diff.

Tests cover the classification rules in Phase 4 decisions 4-5:
added/deleted/modified/moved/dependency symbols, unique vs ambiguous moves,
export-stripped signature comparison, and the optional-parameter-only
signature distinction (c020 vs c022).
"""

from __future__ import annotations

from codeatlas.analysis.symbol_diff import (
    SymbolDiffInput,
    compute_symbol_changes,
)
from codeatlas.contracts import ChangeKind, RelationKind, SymbolKind
from codeatlas.domain.change import SignatureChangeClass
from codeatlas.domain.relations import RelationRecord, ResolutionState
from codeatlas.domain.repository import FileClassification, FileRecord
from codeatlas.domain.symbols import SymbolRecord
from codeatlas.parsing.python_parser import PythonParser
from codeatlas.parsing.registry import ParseRequest


def _parse(
    source: str,
    path: str = "src/payments/service.py",
) -> tuple[FileRecord, tuple[SymbolRecord, ...]]:
    content = source.encode("utf-8")
    file_id = f"file_{path}"
    record = FileRecord(
        file_id=file_id,
        relative_path=path,
        display_path=path,
        content_hash="hash",
        size_bytes=len(content),
        line_count=content.count(b"\n") + (0 if content.endswith(b"\n") else 1),
        language="python",
        classification=FileClassification.SOURCE_CODE,
    )
    result = PythonParser().parse(
        ParseRequest(
            repository_id="repo_1",
            snapshot_id="snap_1",
            file_id=file_id,
            relative_path=path,
            language="python",
            content=content,
        )
    )
    return record, result.symbols


def _input(
    symbols: tuple[SymbolRecord, ...],
    paths: dict[str, str],
) -> SymbolDiffInput:
    return SymbolDiffInput(
        symbols=symbols,
        relations=(),
        file_paths=paths,
    )


def _path_dict(path: str) -> dict[str, str]:
    return {f"file_{path}": path}


def test_added_symbol_detected() -> None:
    _, base_symbols = _parse("")
    _, target_symbols = _parse("def capture() -> str:\n    return 'ok'\n")

    changes = compute_symbol_changes(
        _input(base_symbols, {}),
        _input(target_symbols, _path_dict("src/payments/service.py")),
    )

    assert len(changes) == 1
    assert changes[0].change_kind is ChangeKind.ADDED
    assert changes[0].qualified_name == "capture"


def test_deleted_symbol_detected() -> None:
    _, base_symbols = _parse("def capture() -> str:\n    return 'ok'\n")
    _, target_symbols = _parse("")

    changes = compute_symbol_changes(
        _input(base_symbols, _path_dict("src/payments/service.py")),
        _input(target_symbols, {}),
    )

    assert len(changes) == 1
    assert changes[0].change_kind is ChangeKind.DELETED
    assert changes[0].qualified_name == "capture"


def test_modified_symbol_with_body_change() -> None:
    _, base_symbols = _parse("def capture() -> str:\n    return 'ok'\n")
    _, target_symbols = _parse("def capture() -> str:\n    return 'changed'\n")

    changes = compute_symbol_changes(
        _input(base_symbols, _path_dict("src/payments/service.py")),
        _input(target_symbols, _path_dict("src/payments/service.py")),
    )

    assert len(changes) == 1
    change = changes[0]
    assert change.change_kind is ChangeKind.MODIFIED
    assert change.signature_change_class is SignatureChangeClass.NONE


def test_modified_symbol_with_signature_change() -> None:
    _, base_symbols = _parse(
        "def capture(key: str) -> str:\n    return key\n"
    )
    _, target_symbols = _parse(
        "def capture(key: str, amount: int) -> str:\n    return key\n"
    )

    changes = compute_symbol_changes(
        _input(base_symbols, _path_dict("src/payments/service.py")),
        _input(target_symbols, _path_dict("src/payments/service.py")),
    )

    assert len(changes) == 1
    change = changes[0]
    assert change.change_kind is ChangeKind.MODIFIED
    assert change.signature_change_class is SignatureChangeClass.OTHER


def test_optional_parameters_only_is_distinct_signature_class() -> None:
    _, base_symbols = _parse(
        "def process(name: str) -> str:\n    return name\n"
    )
    _, target_symbols = _parse(
        "def process(name: str, timeout: int = 30) -> str:\n    return name\n"
    )

    changes = compute_symbol_changes(
        _input(base_symbols, _path_dict("src/payments/service.py")),
        _input(target_symbols, _path_dict("src/payments/service.py")),
    )

    assert len(changes) == 1
    change = changes[0]
    assert (
        change.signature_change_class
        is SignatureChangeClass.ONLY_OPTIONAL_PARAMETERS_ADDED
    )


def test_moved_symbol_detected_across_files() -> None:
    _, base_symbols = _parse(
        "def process() -> str:\n    return 'ok'\n", "src/base.py"
    )
    _, target_symbols = _parse(
        "def process() -> str:\n    return 'ok'\n", "src/target.py"
    )

    changes = compute_symbol_changes(
        _input(base_symbols, _path_dict("src/base.py")),
        _input(target_symbols, _path_dict("src/target.py")),
    )

    assert len(changes) == 1
    change = changes[0]
    assert change.change_kind is ChangeKind.MOVED
    assert change.file_path == "src/target.py"
    assert change.base_file_path == "src/base.py"


def test_ambiguous_move_falls_back_to_delete_add() -> None:
    # Two files on each side contain the same qualified name.
    _, base_a = _parse("def process() -> str:\n    return 'a'\n", "src/a.py")
    _, base_b = _parse("def process() -> str:\n    return 'b'\n", "src/b.py")
    _, target_x = _parse("def process() -> str:\n    return 'x'\n", "src/x.py")
    _, target_y = _parse("def process() -> str:\n    return 'y'\n", "src/y.py")

    changes = compute_symbol_changes(
        _input(
            base_a + base_b,
            {"file_src/a.py": "src/a.py", "file_src/b.py": "src/b.py"},
        ),
        _input(
            target_x + target_y,
            {"file_src/x.py": "src/x.py", "file_src/y.py": "src/y.py"},
        ),
    )

    kinds = {change.change_kind for change in changes}
    assert ChangeKind.MOVED not in kinds
    assert ChangeKind.ADDED in kinds
    assert ChangeKind.DELETED in kinds
    assert len(changes) == 4


def test_dependency_change_detected_when_content_unchanged() -> None:
    from codeatlas.contracts import Derivation

    _, base_symbols = _parse("def render() -> str:\n    return 'ok'\n")
    _, target_symbols = _parse("def render() -> str:\n    return 'ok'\n")

    base_symbol = next(s for s in base_symbols if s.qualified_name == "render")
    target_symbol = next(s for s in target_symbols if s.qualified_name == "render")

    base_relations = (
        RelationRecord(
            relation_id="rel_1",
            source_symbol_id=base_symbol.symbol_id,
            target_symbol_id=None,
            file_id=base_symbol.file_id,
            kind=RelationKind.CALLS,
            target_hint="total",
            resolution=ResolutionState.UNRESOLVED,
            derivation=Derivation.HIGH_CONFIDENCE_HEURISTIC,
            confidence=0.7,
            start_line=2,
            end_line=2,
            candidate_count=0,
        ),
    )
    target_relations = (
        RelationRecord(
            relation_id="rel_1",
            source_symbol_id=target_symbol.symbol_id,
            target_symbol_id="sym_total",
            file_id=target_symbol.file_id,
            kind=RelationKind.CALLS,
            target_hint="total",
            resolution=ResolutionState.RESOLVED,
            derivation=Derivation.STATIC_RESOLVED,
            confidence=0.95,
            start_line=2,
            end_line=2,
            candidate_count=1,
        ),
    )

    changes = compute_symbol_changes(
        SymbolDiffInput(
            symbols=base_symbols,
            relations=base_relations,
            file_paths={base_symbol.file_id: "src/payments/service.py"},
        ),
        SymbolDiffInput(
            symbols=target_symbols,
            relations=target_relations,
            file_paths={target_symbol.file_id: "src/payments/service.py"},
        ),
    )

    assert len(changes) == 1
    assert changes[0].change_kind is ChangeKind.DEPENDENCY


def test_import_binding_change_is_a_dependency_change() -> None:
    """c011: adding an import for a name a symbol already calls changes how
    that call resolves, even when the resolver lands on the same target both
    times. The binding lives on the module, which the diff excludes, so the
    comparison must carry it onto the referencing symbol's edges."""
    from codeatlas.contracts import Derivation

    source = "def render() -> str:\n    return total()\n"
    _, base_symbols = _parse(source)
    _, target_symbols = _parse(source)

    base_symbol = next(s for s in base_symbols if s.qualified_name == "render")
    target_symbol = next(s for s in target_symbols if s.qualified_name == "render")

    def calls_edge(symbol: SymbolRecord) -> RelationRecord:
        return RelationRecord(
            relation_id="rel_calls",
            source_symbol_id=symbol.symbol_id,
            target_symbol_id="sym_total",
            file_id=symbol.file_id,
            kind=RelationKind.CALLS,
            target_hint="total",
            resolution=ResolutionState.RESOLVED,
            derivation=Derivation.STATIC_RESOLVED,
            confidence=0.95,
            start_line=2,
            end_line=2,
            candidate_count=1,
        )

    module = next(s for s in base_symbols if s.kind is SymbolKind.MODULE)
    import_edge = RelationRecord(
        relation_id="rel_import",
        source_symbol_id=module.symbol_id,
        target_symbol_id="sym_total",
        file_id=base_symbol.file_id,
        kind=RelationKind.IMPORTS,
        target_hint="total",
        resolution=ResolutionState.RESOLVED,
        derivation=Derivation.STATIC_RESOLVED,
        confidence=0.95,
        start_line=1,
        end_line=1,
        candidate_count=1,
        module_hint="./orders",
    )

    changes = compute_symbol_changes(
        SymbolDiffInput(
            symbols=base_symbols,
            relations=(calls_edge(base_symbol),),
            file_paths={base_symbol.file_id: "src/payments/service.py"},
        ),
        SymbolDiffInput(
            symbols=target_symbols,
            relations=(calls_edge(target_symbol), import_edge),
            file_paths={target_symbol.file_id: "src/payments/service.py"},
        ),
    )

    assert [c.change_kind for c in changes] == [ChangeKind.DEPENDENCY]
    assert changes[0].qualified_name == "render"
    # The citation runs from the binding to the reference that resolves
    # through it (c011: the import line through the call line).
    assert changes[0].evidence_start_line == 1
    assert changes[0].evidence_end_line == 2


def test_unrelated_import_change_is_not_a_dependency_change() -> None:
    """The converse guard: an import the symbol never references cannot mark
    it dependency-changed, or every import edit would flag every symbol in
    the file."""
    from codeatlas.contracts import Derivation

    source = "def render() -> str:\n    return 'ok'\n"
    _, base_symbols = _parse(source)
    _, target_symbols = _parse(source)

    base_symbol = next(s for s in base_symbols if s.qualified_name == "render")
    target_symbol = next(s for s in target_symbols if s.qualified_name == "render")
    module = next(s for s in base_symbols if s.kind is SymbolKind.MODULE)

    import_edge = RelationRecord(
        relation_id="rel_import",
        source_symbol_id=module.symbol_id,
        target_symbol_id="sym_other",
        file_id=base_symbol.file_id,
        kind=RelationKind.IMPORTS,
        target_hint="other",
        resolution=ResolutionState.RESOLVED,
        derivation=Derivation.STATIC_RESOLVED,
        confidence=0.95,
        start_line=1,
        end_line=1,
        candidate_count=1,
        module_hint="./other",
    )

    changes = compute_symbol_changes(
        SymbolDiffInput(
            symbols=base_symbols,
            relations=(),
            file_paths={base_symbol.file_id: "src/payments/service.py"},
        ),
        SymbolDiffInput(
            symbols=target_symbols,
            relations=(import_edge,),
            file_paths={target_symbol.file_id: "src/payments/service.py"},
        ),
    )

    assert changes == ()


def test_module_symbols_are_excluded_from_changed_symbols() -> None:
    _, base_symbols = _parse("def capture() -> str:\n    return 'ok'\n")
    _, target_symbols = _parse("def capture() -> str:\n    return 'changed'\n")

    changes = compute_symbol_changes(
        _input(base_symbols, _path_dict("src/payments/service.py")),
        _input(target_symbols, _path_dict("src/payments/service.py")),
    )

    assert not any(change.symbol_kind is SymbolKind.MODULE for change in changes)


def test_public_visibility_carried_to_change() -> None:
    _, base_symbols = _parse("def capture() -> str:\n    return 'ok'\n")
    _, target_symbols = _parse("def capture() -> str:\n    return 'changed'\n")

    changes = compute_symbol_changes(
        _input(base_symbols, _path_dict("src/payments/service.py")),
        _input(target_symbols, _path_dict("src/payments/service.py")),
    )

    assert len(changes) == 1
    assert changes[0].public is True


def test_export_keyword_is_stripped_for_signature_comparison() -> None:
    # Python has no export keyword; test that the signature text is compared
    # after normalization. The same logic is used for TypeScript export stripping.
    _, base_symbols = _parse("def capture(key: str) -> str:\n    return key\n")
    _, target_symbols = _parse(
        "def capture(key: str, extra: int) -> str:\n    return key\n"
    )

    changes = compute_symbol_changes(
        _input(base_symbols, _path_dict("src/payments/service.py")),
        _input(target_symbols, _path_dict("src/payments/service.py")),
    )

    assert len(changes) == 1
    assert changes[0].signature_change_class is SignatureChangeClass.OTHER


# --- Container folding and dependency discipline (P4-10 corpus corrections) ---


def _record(
    symbol_id: str,
    kind: SymbolKind,
    qualified_name: str,
    *,
    file_id: str = "file_src/orders.ts",
    signature: str | None = None,
    start_line: int = 1,
    end_line: int = 2,
    content_hash: str = "h1",
) -> SymbolRecord:
    return SymbolRecord(
        symbol_id=symbol_id,
        symbol_version_id=f"{symbol_id}_v",
        file_id=file_id,
        kind=kind,
        name=qualified_name.rsplit(".", 1)[-1],
        qualified_name=qualified_name,
        module_path="mod",
        signature=signature,
        start_line=start_line,
        end_line=end_line,
        start_byte=0,
        end_byte=0,
        content_hash=content_hash,
        visibility="public",
    )


_CLASS_SOURCE = (
    "class PaymentService:\n"
    "    def capture(self) -> str:\n"
    "        return 'a'\n"
    "\n"
    "    def refund(self) -> str:\n"
    "        return 'b'\n"
)


def test_a_class_whose_only_change_is_a_members_body_reports_the_member() -> None:
    """c001-c004: one edit, one change. The class's hash moves because the
    member's text is inside its range; reporting both double-counts the edit."""
    _, base_symbols = _parse(_CLASS_SOURCE)
    _, target_symbols = _parse(_CLASS_SOURCE.replace("'a'", "'changed'"))

    changes = compute_symbol_changes(
        _input(base_symbols, _path_dict("src/payments/service.py")),
        _input(target_symbols, _path_dict("src/payments/service.py")),
    )

    assert [change.qualified_name for change in changes] == [
        "PaymentService.capture"
    ]


def test_a_class_with_its_own_signature_change_is_still_reported() -> None:
    paths = {"file_src/orders.ts": "src/orders.ts"}
    base = (
        _record("sym_k", SymbolKind.CLASS, "K", signature="class K(A)",
                start_line=1, end_line=4, content_hash="k1"),
        _record("sym_m", SymbolKind.FUNCTION, "K.m",
                start_line=2, end_line=3, content_hash="m1"),
    )
    target = (
        _record("sym_k", SymbolKind.CLASS, "K", signature="class K(B)",
                start_line=1, end_line=4, content_hash="k2"),
        _record("sym_m", SymbolKind.FUNCTION, "K.m",
                start_line=2, end_line=3, content_hash="m2"),
    )

    changes = compute_symbol_changes(
        _input(base, paths), _input(target, paths)
    )

    assert {change.qualified_name for change in changes} == {"K", "K.m"}


def test_a_deleted_class_reports_only_itself_not_each_member() -> None:
    """c006: the deletion of `FakeStore` is one fact, not one per member."""
    source = (
        "class FakeStore:\n"
        "    def claim(self, key: str) -> str:\n"
        "        return key\n"
    )
    _, base_symbols = _parse(source, "tests/test_service.py")
    _, target_symbols = _parse("", "tests/test_service.py")

    changes = compute_symbol_changes(
        _input(base_symbols, _path_dict("tests/test_service.py")),
        _input(target_symbols, _path_dict("tests/test_service.py")),
    )

    assert [change.qualified_name for change in changes] == ["FakeStore"]
    assert changes[0].change_kind is ChangeKind.DELETED


def test_a_types_member_change_folds_into_the_type() -> None:
    """c007: a field is the type's shape; `Order` is the changed contract."""
    paths = {"file_src/orders.ts": "src/orders.ts"}
    base = (
        _record("sym_order", SymbolKind.INTERFACE, "Order",
                start_line=1, end_line=3, content_hash="o1"),
        _record("sym_id", SymbolKind.FIELD, "Order.id",
                signature="id: string", start_line=2, end_line=2,
                content_hash="f1"),
    )
    target = (
        _record("sym_order", SymbolKind.INTERFACE, "Order",
                start_line=1, end_line=3, content_hash="o2"),
        _record("sym_id", SymbolKind.FIELD, "Order.id",
                signature="id: number", start_line=2, end_line=2,
                content_hash="f2"),
    )

    changes = compute_symbol_changes(
        _input(base, paths), _input(target, paths)
    )

    assert [change.qualified_name for change in changes] == ["Order"]


def test_a_dependency_on_a_deleted_symbol_is_impact_not_a_change() -> None:
    """c006: the deletion is the change; a surviving referrer whose edge no
    longer resolves is reported by impact's unresolved dependents, not as a
    second changed symbol."""
    from codeatlas.contracts import Derivation

    paths = {"file_tests/test_service.py": "tests/test_service.py"}
    caller = _record(
        "sym_test", SymbolKind.FUNCTION, "test_capture",
        file_id="file_tests/test_service.py", start_line=1, end_line=2,
    )
    referent = _record(
        "sym_fake", SymbolKind.CLASS, "FakeStore",
        file_id="file_tests/test_service.py", start_line=4, end_line=6,
    )
    base_relations = (
        RelationRecord(
            relation_id="rel_1",
            source_symbol_id="sym_test",
            target_symbol_id="sym_fake",
            file_id="file_tests/test_service.py",
            kind=RelationKind.REFERENCES,
            target_hint="FakeStore",
            resolution=ResolutionState.RESOLVED,
            derivation=Derivation.STATIC_RESOLVED,
            confidence=0.95,
            start_line=1,
            end_line=1,
            candidate_count=1,
        ),
    )
    target_relations = (
        RelationRecord(
            relation_id="rel_1",
            source_symbol_id="sym_test",
            target_symbol_id=None,
            file_id="file_tests/test_service.py",
            kind=RelationKind.REFERENCES,
            target_hint="FakeStore",
            resolution=ResolutionState.UNRESOLVED,
            derivation=Derivation.HIGH_CONFIDENCE_HEURISTIC,
            confidence=0.7,
            start_line=1,
            end_line=1,
            candidate_count=0,
        ),
    )

    changes = compute_symbol_changes(
        SymbolDiffInput(
            symbols=(caller, referent),
            relations=base_relations,
            file_paths=paths,
        ),
        SymbolDiffInput(
            symbols=(caller,),
            relations=target_relations,
            file_paths=paths,
        ),
    )

    assert [change.qualified_name for change in changes] == ["FakeStore"]
    assert changes[0].change_kind is ChangeKind.DELETED


def test_heuristic_edges_do_not_create_dependency_changes() -> None:
    """c016: route and mention matching are heuristics; a heuristic edge that
    re-resolves differently is not a deterministic dependency change."""
    from codeatlas.contracts import Derivation
    from codeatlas.domain.relations import MENTION_HINT

    paths = {"file_docs/flow.md": "docs/flow.md"}
    section = _record(
        "sym_flow", SymbolKind.DOCUMENT_SECTION, "Order flow",
        file_id="file_docs/flow.md", start_line=1, end_line=4,
    )
    target_relations = (
        RelationRecord(
            relation_id="rel_1",
            source_symbol_id="sym_flow",
            target_symbol_id="sym_elsewhere",
            file_id="file_docs/flow.md",
            kind=RelationKind.REFERENCES,
            target_hint="loadOrder",
            resolution=ResolutionState.RESOLVED,
            derivation=Derivation.LOW_CONFIDENCE_HEURISTIC,
            confidence=0.4,
            start_line=2,
            end_line=2,
            candidate_count=1,
            module_hint=MENTION_HINT,
        ),
    )

    changes = compute_symbol_changes(
        SymbolDiffInput(symbols=(section,), relations=(), file_paths=paths),
        SymbolDiffInput(
            symbols=(section,), relations=target_relations, file_paths=paths
        ),
    )

    assert changes == ()


def test_keyword_only_marker_is_not_a_parameter() -> None:
    """c022: gaining `*, strict: bool = False` is only-optional-added; the
    bare `*` is a separator, not a parameter."""
    from codeatlas.analysis.symbol_diff import _signature_change_class

    assert (
        _signature_change_class(
            "def process(value: str) -> str",
            "def process(value: str, *, strict: bool = False) -> str",
        )
        is SignatureChangeClass.ONLY_OPTIONAL_PARAMETERS_ADDED
    )


# --- Same-name keys in different files pair within their file (ADR-0042) ---


def test_identical_key_in_two_files_reports_nothing() -> None:
    """A key name shared by two files is not ambiguous, and an unchanged
    repository must produce no change at all.

    Matching on `(kind, qualified_name)` alone made two files declaring
    `cases` a two-versus-two match, which fell to the ambiguous branch and
    reported both as deleted *and* both as added -- on byte-identical content.
    """
    paths = {"file_a.json": "a.json", "file_b.json": "b.json"}
    symbols = (
        _record("sym_a", SymbolKind.CONFIG_KEY, "cases", file_id="file_a.json"),
        _record("sym_b", SymbolKind.CONFIG_KEY, "cases", file_id="file_b.json"),
    )

    changes = compute_symbol_changes(
        SymbolDiffInput(symbols=symbols, relations=(), file_paths=paths),
        SymbolDiffInput(symbols=symbols, relations=(), file_paths=paths),
    )

    assert changes == ()


def test_shared_key_name_reports_only_the_file_that_changed() -> None:
    """One edit is one change, even when the key name is not unique."""
    paths = {"file_a.json": "a.json", "file_b.json": "b.json"}
    base = (
        _record("sym_a", SymbolKind.CONFIG_KEY, "port", file_id="file_a.json"),
        _record("sym_b", SymbolKind.CONFIG_KEY, "port", file_id="file_b.json"),
    )
    target = (
        _record(
            "sym_a",
            SymbolKind.CONFIG_KEY,
            "port",
            file_id="file_a.json",
            content_hash="changed",
        ),
        _record("sym_b", SymbolKind.CONFIG_KEY, "port", file_id="file_b.json"),
    )

    changes = compute_symbol_changes(
        SymbolDiffInput(symbols=base, relations=(), file_paths=paths),
        SymbolDiffInput(symbols=target, relations=(), file_paths=paths),
    )

    assert len(changes) == 1
    assert changes[0].change_kind is ChangeKind.MODIFIED
    assert changes[0].file_path == "a.json"


def test_cross_file_move_still_detected_when_name_is_unique() -> None:
    """The move rule is unchanged: a name on exactly one side of each file,
    with no same-file partner, is still carried across as a move."""
    paths = {"file_a.json": "a.json", "file_b.json": "b.json"}
    base = (_record("sym_a", SymbolKind.CONFIG_KEY, "port", file_id="file_a.json"),)
    target = (_record("sym_b", SymbolKind.CONFIG_KEY, "port", file_id="file_b.json"),)

    changes = compute_symbol_changes(
        SymbolDiffInput(symbols=base, relations=(), file_paths=paths),
        SymbolDiffInput(symbols=target, relations=(), file_paths=paths),
    )

    assert len(changes) == 1
    assert changes[0].change_kind is ChangeKind.MOVED


def test_config_ancestor_folds_into_the_leaf_that_changed() -> None:
    """One edit is one change, for a config key as much as for a class.

    A mapping key's value *is* its subtree, so editing `service.api.http.port`
    also moves the hash of `service.api.http`, `service.api` and `service`.
    Reporting all four restates one edit four times, each entry looking like a
    duplicate of the last.
    """
    paths = {"file_config.yaml": "config.yaml"}
    ancestors = ("service", "service.api", "service.api.http")
    leaf = "service.api.http.port"

    def side(hash_of_leaf: str) -> tuple[SymbolRecord, ...]:
        records = [
            _record(
                f"sym_{name}",
                SymbolKind.CONFIG_KEY,
                name,
                file_id="file_config.yaml",
                start_line=1,
                end_line=9,
                content_hash=f"outer-{hash_of_leaf}",
            )
            for name in ancestors
        ]
        records.append(
            _record(
                "sym_leaf",
                SymbolKind.CONFIG_KEY,
                leaf,
                file_id="file_config.yaml",
                start_line=4,
                end_line=4,
                content_hash=hash_of_leaf,
            )
        )
        return tuple(records)

    changes = compute_symbol_changes(
        SymbolDiffInput(symbols=side("h1"), relations=(), file_paths=paths),
        SymbolDiffInput(symbols=side("h2"), relations=(), file_paths=paths),
    )

    assert [c.qualified_name for c in changes] == [leaf]


def test_config_key_still_reports_when_it_alone_changed() -> None:
    """Folding must not swallow a container that changed on its own."""
    paths = {"file_config.yaml": "config.yaml"}
    base = (
        _record(
            "sym_service",
            SymbolKind.CONFIG_KEY,
            "service",
            file_id="file_config.yaml",
            start_line=1,
            end_line=9,
            content_hash="h1",
        ),
    )
    target = (
        _record(
            "sym_service",
            SymbolKind.CONFIG_KEY,
            "service",
            file_id="file_config.yaml",
            start_line=1,
            end_line=9,
            content_hash="h2",
        ),
    )

    changes = compute_symbol_changes(
        SymbolDiffInput(symbols=base, relations=(), file_paths=paths),
        SymbolDiffInput(symbols=target, relations=(), file_paths=paths),
    )

    assert [c.qualified_name for c in changes] == ["service"]


def test_intermediate_config_keys_fold_on_their_dotted_path() -> None:
    """Containment for a config key is its dotted path, not its line range.

    ADR-0041 gave every nested key its own line, so `service.api` and
    `service.api.http` are one-line ranges that do not contain the leaf's line.
    Only the top-level key still spanned the block, so line containment folded
    that one and left the intermediates restating the same edit.
    """
    paths = {"file_config.yaml": "config.yaml"}

    def side(leaf_hash: str) -> tuple[SymbolRecord, ...]:
        return (
            _record(
                "sym_service",
                SymbolKind.CONFIG_KEY,
                "service",
                file_id="file_config.yaml",
                start_line=1,
                end_line=5,
                content_hash=f"a-{leaf_hash}",
            ),
            _record(
                "sym_api",
                SymbolKind.CONFIG_KEY,
                "service.api",
                file_id="file_config.yaml",
                start_line=2,
                end_line=2,
                content_hash=f"b-{leaf_hash}",
            ),
            _record(
                "sym_http",
                SymbolKind.CONFIG_KEY,
                "service.api.http",
                file_id="file_config.yaml",
                start_line=3,
                end_line=3,
                content_hash=f"c-{leaf_hash}",
            ),
            _record(
                "sym_port",
                SymbolKind.CONFIG_KEY,
                "service.api.http.port",
                file_id="file_config.yaml",
                start_line=4,
                end_line=4,
                content_hash=leaf_hash,
            ),
        )

    changes = compute_symbol_changes(
        SymbolDiffInput(symbols=side("h1"), relations=(), file_paths=paths),
        SymbolDiffInput(symbols=side("h2"), relations=(), file_paths=paths),
    )

    assert [c.qualified_name for c in changes] == ["service.api.http.port"]


def test_a_sibling_config_key_is_not_folded_by_a_prefix_that_only_looks_alike()\
        -> None:
    """`service.apikey` is not inside `service.api`: the boundary is the dot."""
    paths = {"file_config.yaml": "config.yaml"}

    def side(suffix: str) -> tuple[SymbolRecord, ...]:
        return (
            _record(
                "sym_api",
                SymbolKind.CONFIG_KEY,
                "service.api",
                file_id="file_config.yaml",
                start_line=2,
                end_line=2,
                content_hash=f"api-{suffix}",
            ),
            _record(
                "sym_apikey",
                SymbolKind.CONFIG_KEY,
                "service.apikey",
                file_id="file_config.yaml",
                start_line=3,
                end_line=3,
                content_hash=f"apikey-{suffix}",
            ),
        )

    changes = compute_symbol_changes(
        SymbolDiffInput(symbols=side("1"), relations=(), file_paths=paths),
        SymbolDiffInput(symbols=side("2"), relations=(), file_paths=paths),
    )

    assert sorted(c.qualified_name for c in changes) == [
        "service.api",
        "service.apikey",
    ]

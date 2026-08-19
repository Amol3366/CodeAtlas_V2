"""The Go adapter's five methods (ADR-0065).

`owner_hint` is the reason this design is not purely declarative: a Go method's
owner is its receiver, which is a field of the method node rather than a lexical
ancestor.
"""

from __future__ import annotations

from tree_sitter import Parser as TreeSitterParser

from codeatlas.contracts import SymbolKind
from codeatlas.parsing.query_backed.engine import TagsBackedParser
from codeatlas.parsing.query_backed.languages.go import GoAdapter
from codeatlas.parsing.registry import ParseRequest

SOURCE = b"""package orders

import (
\t"errors"
\t"myapp/internal/payments"
)

type OrderService struct {
\tpayments *payments.Service
}

func NewOrderService(p *payments.Service) *OrderService {
\treturn &OrderService{payments: p}
}

func (s *OrderService) Audit(reason string) error {
\treturn errors.New(reason)
}

func (s *OrderService) capture(orderID string) error {
\treturn s.payments.Charge(orderID)
}
"""


def _root(source: bytes = SOURCE) -> tuple[object, GoAdapter]:
    adapter = GoAdapter()
    tree = TreeSitterParser(adapter.profile.grammar).parse(source)
    return tree.root_node, adapter


def _request(content: bytes = SOURCE) -> ParseRequest:
    return ParseRequest(
        repository_id="repo_test",
        snapshot_id="snap_test",
        file_id="file_test",
        relative_path="internal/orders/service.go",
        language="go",
        content=content,
    )


def test_module_path_is_the_directory_not_the_package_clause() -> None:
    root, adapter = _root()
    assert adapter.module_path(root, SOURCE, "internal/orders/service.go") == (
        "internal.orders"
    )


def test_a_method_is_qualified_by_its_receiver_not_by_lexical_scope() -> None:
    """The measured case: the receiver is a field, not an ancestor."""
    result = TagsBackedParser(GoAdapter()).parse(_request())

    names = {symbol.qualified_name for symbol in result.symbols}
    assert "OrderService.Audit" in names
    assert "OrderService.capture" in names
    # A plain function has no receiver and stays unqualified.
    assert "NewOrderService" in names


def test_a_type_and_a_function_get_their_kinds() -> None:
    result = TagsBackedParser(GoAdapter()).parse(_request())

    kinds = {symbol.qualified_name: symbol.kind for symbol in result.symbols}
    assert kinds["OrderService"] is SymbolKind.CLASS
    assert kinds["NewOrderService"] is SymbolKind.FUNCTION
    assert kinds["OrderService.Audit"] is SymbolKind.METHOD


def test_visibility_follows_gos_capitalisation_rule() -> None:
    result = TagsBackedParser(GoAdapter()).parse(_request())

    visibility = {symbol.qualified_name: symbol.visibility for symbol in result.symbols}
    assert visibility["OrderService.Audit"] == "public"
    assert visibility["OrderService.capture"] == "private"


def test_imports_bind_the_last_path_segment() -> None:
    root, adapter = _root()

    refs = list(adapter.imports(root, SOURCE, "file_x", "sym_mod"))
    hints = {ref.target_hint for ref in refs}
    modules = {ref.module_hint for ref in refs}
    assert "payments" in hints
    assert "errors" in hints
    assert "myapp.internal.payments" in modules

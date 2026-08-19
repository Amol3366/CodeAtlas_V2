"""The Java adapter's five methods (ADR-0065)."""

from __future__ import annotations

from tree_sitter import Parser as TreeSitterParser

from codeatlas.parsing.query_backed.languages.java import JavaAdapter

SOURCE = b"""package com.shop.orders;

import com.shop.payments.PaymentService;
import java.util.List;

public class OrderService {
    private int count;
    public void audit(String reason) {}
}
"""


def _root(source: bytes = SOURCE) -> tuple[object, JavaAdapter]:
    adapter = JavaAdapter()
    tree = TreeSitterParser(adapter.profile.grammar).parse(source)
    return tree.root_node, adapter


def test_module_path_comes_from_the_package_declaration() -> None:
    root, adapter = _root()
    assert (
        adapter.module_path(root, SOURCE, "src/main/java/com/shop/orders/X.java")
        == "com.shop.orders"
    )


def test_module_path_falls_back_to_the_path_when_no_package_is_declared() -> None:
    source = b"public class Loose {}\n"
    root, adapter = _root(source)
    assert adapter.module_path(root, source, "src/Loose.java") == "src.Loose"


def test_a_method_is_qualified_by_its_enclosing_class() -> None:
    root, adapter = _root()
    assert adapter.qualified_name(root, "audit", ["OrderService"], SOURCE) == (
        "OrderService.audit"
    )


def test_imports_name_the_bound_symbol_not_the_package() -> None:
    # ADR-0039's rule applied to Java: `import x.Y` binds `Y`.
    root, adapter = _root()
    hints = {
        ref.target_hint for ref in adapter.imports(root, SOURCE, "file_x", "sym_mod")
    }
    assert "PaymentService" in hints
    assert "List" in hints

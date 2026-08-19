"""The Rust adapter (ADR-0065).

Rust needs `owner_hint` because `impl_item` carries its owner on the `type`
field rather than a `name` field, so the engine's generic scope walk finds
nothing. It also exercises the engine's span deduplication: Rust's tags.scm
matches a method as both `definition.method` and `definition.function`.
"""

from __future__ import annotations

from tree_sitter import Parser as TreeSitterParser

from codeatlas.contracts import SymbolKind
from codeatlas.parsing.query_backed.engine import TagsBackedParser
from codeatlas.parsing.query_backed.languages.rust import RustAdapter
from codeatlas.parsing.registry import ParseRequest

SOURCE = b"""use crate::payments::Service;
use std::collections::HashMap;

pub trait Auditable {
    fn audit(&self, reason: &str);
}

pub struct OrderService {
    payments: Service,
}

impl Auditable for OrderService {
    fn audit(&self, reason: &str) {}
}

impl OrderService {
    pub fn capture(&self, order_id: &str) -> u32 {
        self.payments.charge(order_id);
        self.audit("captured");
        1
    }

    fn hidden(&self) {}
}

pub fn standalone() {}
"""


def _request(content: bytes = SOURCE) -> ParseRequest:
    return ParseRequest(
        repository_id="repo_test",
        snapshot_id="snap_test",
        file_id="file_test",
        relative_path="src/orders/service.rs",
        language="rust",
        content=content,
    )


def _symbols() -> dict[str, SymbolKind]:
    result = TagsBackedParser(RustAdapter()).parse(_request())
    return {symbol.qualified_name: symbol.kind for symbol in result.symbols}


def test_a_method_is_qualified_by_its_impl_type() -> None:
    symbols = _symbols()

    assert "OrderService.capture" in symbols
    assert "OrderService.audit" in symbols
    assert symbols["OrderService.capture"] is SymbolKind.METHOD


def test_a_method_is_not_also_stored_as_a_free_function() -> None:
    """Rust's tags.scm matches a method under two patterns; only one survives."""
    result = TagsBackedParser(RustAdapter()).parse(_request())

    capture_symbols = [s for s in result.symbols if s.name == "capture"]
    assert len(capture_symbols) == 1
    assert capture_symbols[0].kind is SymbolKind.METHOD


def test_a_free_function_stays_a_function() -> None:
    symbols = _symbols()

    assert symbols["standalone"] is SymbolKind.FUNCTION


def test_a_trait_and_a_struct_get_their_kinds() -> None:
    symbols = _symbols()

    assert symbols["Auditable"] is SymbolKind.INTERFACE
    assert symbols["OrderService"] is SymbolKind.CLASS


def test_visibility_follows_the_pub_modifier() -> None:
    result = TagsBackedParser(RustAdapter()).parse(_request())
    visibility = {s.qualified_name: s.visibility for s in result.symbols}

    assert visibility["OrderService.capture"] == "public"
    assert visibility["OrderService.hidden"] == "private"


def test_a_use_path_binds_its_last_segment_and_drops_crate() -> None:
    adapter = RustAdapter()
    tree = TreeSitterParser(adapter.profile.grammar).parse(SOURCE)

    refs = list(adapter.imports(tree.root_node, SOURCE, "file_x", "sym_mod"))
    by_target = {ref.target_hint: ref.module_hint for ref in refs}

    # `crate` is a language keyword, so stripping it is safe -- unlike Go's
    # go.mod prefix, which is external configuration.
    assert by_target["Service"] == "payments"
    assert by_target["HashMap"] == "std.collections"

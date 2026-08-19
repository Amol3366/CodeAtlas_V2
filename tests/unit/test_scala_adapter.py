"""The Scala adapter (ADR-0065).

Scala is the Java-shaped case: a declared `package` and lexical ownership, so it
needs no `owner_hint`. The same engine covers it and Go, which is the design's
claim. It also carries the weakest shipped `tags.scm` of the four -- see the
declared limitations at the bottom of this file.
"""

from __future__ import annotations

import pytest
from tree_sitter import Parser as TreeSitterParser

from codeatlas.contracts import SymbolKind
from codeatlas.parsing.query_backed.engine import TagsBackedParser
from codeatlas.parsing.query_backed.languages.scala import ScalaAdapter
from codeatlas.parsing.registry import ParseRequest

SOURCE = b"""package shop.orders

import shop.payments.PaymentService

trait Auditable {
  def audit(reason: String): Unit
}

class OrderService(payments: PaymentService) extends Auditable {
  def capture(orderId: String): Int = {
    helper(orderId)
    payments.charge(orderId)
    1
  }

  private def hidden(): Unit = {}
}

object OrderService {
  val MaxItems: Int = 50
}
"""


def _request(content: bytes = SOURCE) -> ParseRequest:
    return ParseRequest(
        repository_id="repo_test",
        snapshot_id="snap_test",
        file_id="file_test",
        relative_path="src/main/scala/shop/orders/OrderService.scala",
        language="scala",
        content=content,
    )


def test_module_path_comes_from_the_package_clause() -> None:
    adapter = ScalaAdapter()
    tree = TreeSitterParser(adapter.profile.grammar).parse(SOURCE)

    assert adapter.module_path(tree.root_node, SOURCE, "x/Y.scala") == "shop.orders"


def test_members_are_qualified_by_their_enclosing_definition() -> None:
    result = TagsBackedParser(ScalaAdapter()).parse(_request())

    names = {symbol.qualified_name for symbol in result.symbols}
    assert "OrderService.capture" in names
    assert "OrderService.MaxItems" in names


def test_a_trait_and_a_class_get_their_kinds() -> None:
    result = TagsBackedParser(ScalaAdapter()).parse(_request())
    kinds = {symbol.qualified_name: symbol.kind for symbol in result.symbols}

    assert kinds["Auditable"] is SymbolKind.INTERFACE
    assert kinds["OrderService"] is SymbolKind.CLASS


def test_scala_is_public_unless_a_modifier_narrows_it() -> None:
    result = TagsBackedParser(ScalaAdapter()).parse(_request())
    visibility = {s.qualified_name: s.visibility for s in result.symbols}

    assert visibility["OrderService.capture"] == "public"
    assert visibility["OrderService.hidden"] == "private"


def test_an_import_binds_its_last_segment() -> None:
    adapter = ScalaAdapter()
    tree = TreeSitterParser(adapter.profile.grammar).parse(SOURCE)

    refs = list(adapter.imports(tree.root_node, SOURCE, "file_x", "sym_mod"))
    by_target = {ref.target_hint: ref.module_hint for ref in refs}

    assert by_target["PaymentService"] == "shop.payments"


def test_a_call_to_a_bare_identifier_is_captured() -> None:
    """`helper(orderId)` -- the one call shape Scala's tags.scm does match."""
    result = TagsBackedParser(ScalaAdapter()).parse(_request())

    assert any(
        ref.kind.value == "CALLS" and ref.target_hint == "helper"
        for ref in result.references
    )


SCALA_CALL_LIMIT = (
    "ADR-0065 Scala slice, measured 2026-08-19. Scala's shipped tags.scm carries "
    "only `(call_expression (identifier) @name) @reference.call`, so a call whose "
    "function is a `field_expression` -- `payments.charge(orderId)`, which is most "
    "Scala calls -- is never captured. Java, Go and Rust all ship a member-call "
    "pattern; Scala does not. Closing it means authoring a supplementary "
    "references query, which the profile contract does not yet carry: it has one "
    "authored query slot, `imports_query`. Recorded rather than fixed, because "
    "widening the contract mid-slice is the scope creep this project forbids."
)


@pytest.mark.xfail(strict=True, reason=SCALA_CALL_LIMIT)
def test_a_method_call_on_a_receiver_is_captured() -> None:
    result = TagsBackedParser(ScalaAdapter()).parse(_request())

    assert any(
        ref.kind.value == "CALLS" and ref.target_hint == "charge"
        for ref in result.references
    )

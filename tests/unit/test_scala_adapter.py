"""The Scala adapter (ADR-0065).

Scala is the Java-shaped case: a declared `package` and lexical ownership, so it
needs no `owner_hint`. The same engine covers it and Go, which is the design's
claim. It also carries the weakest shipped `tags.scm` of the four -- see the
declared limitations at the bottom of this file.
"""

from __future__ import annotations

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


# Ruled 2026-08-19 (ADR-0067): the profile contract gained a second authored
# query slot and Scala fills it, so this no longer xfails. The limit text
# above is kept verbatim as the reasoning the decision was made on.
def test_a_method_call_on_a_receiver_is_captured() -> None:
    """`payments.charge(id)` produces a CALLS edge (ADR-0067).

    Was a `strict` xfail: Scala's shipped `tags.scm` matches only
    `(call_expression (identifier) @name)`, so a call on a receiver -- most
    real Scala -- was invisible. The supplementary `scala.references.scm`
    captures the `field_expression`'s `field`, which is the method name.
    """
    result = TagsBackedParser(ScalaAdapter()).parse(_request())

    assert any(
        ref.kind.value == "CALLS" and ref.target_hint == "charge"
        for ref in result.references
    )


def test_a_bare_call_is_still_captured_alongside_member_calls() -> None:
    """The supplementary query adds coverage; it does not replace any.

    `helper(orderId)` is matched by the grammar's shipped `tags.scm` and
    `payments.charge(orderId)` only by `scala.references.scm` (ADR-0067). Both
    must survive, because the extractor now runs two queries and the failure
    worth guarding against is one shadowing the other -- a supplementary query
    that quietly replaced the shipped one would trade a known gap for a silent
    regression.

    Asserted together in one test on purpose: separately, each passes while the
    other is broken.
    """
    result = TagsBackedParser(ScalaAdapter()).parse(_request())
    called = {ref.target_hint for ref in result.references if ref.kind.value == "CALLS"}

    assert {"helper", "charge"} <= called, (
        f"expected both the bare and the member call, got {sorted(called)}"
    )


def test_a_member_call_is_recorded_once() -> None:
    """Two queries must not store one call twice.

    `parts` spans both queries so an identical name on one line is treated as
    the same reference. If a future query captured `charge` as well, this fails
    rather than silently doubling an edge -- and a duplicated CALLS edge would
    inflate impact analysis, which is the product's core claim.
    """
    result = TagsBackedParser(ScalaAdapter()).parse(_request())
    charges = [
        ref
        for ref in result.references
        if ref.kind.value == "CALLS" and ref.target_hint == "charge"
    ]

    assert len(charges) == 1, f"expected one CALLS edge for charge, got {len(charges)}"

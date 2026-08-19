; Member calls, which Scala's shipped tags.scm does not capture (ADR-0067).
;
; Its only call pattern is `(call_expression (identifier) @name) @reference.call`,
; which matches a call to a bare identifier -- `log(x)`. A call on a receiver,
; `payments.charge(id)`, has a `field_expression` as its `function`, so most real
; Scala calls produced no edge at all. Java, Go and Rust all ship a member-call
; pattern; Scala is the only one of the four that does not.
;
; The method name is the `field`, not the `value`: in `payments.charge`, the edge
; targets `charge`. Capturing `value` would target the receiver and assert that a
; variable was called, which is a different and false claim.
;
; Chained calls fall out of this: `a.b.c(x)` matches once, on `c`, because the
; inner `a.b` is the `value` of the outer field_expression rather than the
; `function` of a call.
(call_expression
  function: (field_expression
    field: (identifier) @name)) @reference.call

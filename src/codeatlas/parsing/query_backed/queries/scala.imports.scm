; No shipped tags.scm captures an import (ADR-0065). This supplies the gap.
; Scala's import_declaration exposes each identifier as a separate child rather
; than one path node, so the statement is captured whole and the adapter reads
; its text. Capturing the children individually yields "shop", "payments",
; "PaymentService" as three unrelated paths.
(import_declaration) @import.statement
(package_clause name: (package_identifier) @package.name)

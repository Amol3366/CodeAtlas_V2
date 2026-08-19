; No shipped tags.scm captures an import (ADR-0065). This supplies the gap.
; `use crate::payments::Service;` -- the argument holds the whole path.
(use_declaration argument: (_) @import.path) @import.statement

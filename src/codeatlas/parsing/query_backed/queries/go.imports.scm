; No shipped tags.scm captures an import (ADR-0065). This supplies the gap.
; Go's import path is a string literal, quotes included, so the adapter trims it.
(import_declaration (import_spec path: (interpreted_string_literal) @import.path)) @import.statement
(import_declaration
  (import_spec_list
    (import_spec path: (interpreted_string_literal) @import.path))) @import.statement
(package_clause (package_identifier) @package.name)

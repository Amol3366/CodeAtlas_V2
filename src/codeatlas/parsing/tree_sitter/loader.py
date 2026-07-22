"""Tree-sitter language loading (error-tolerant parsing, Blueprint §4.4.4).

Parsers are cached per process (via ``lru_cache``) so ProcessPoolExecutor
workers pay the construction cost once. Tree-sitter is used for its
error-tolerant tree: it still yields ``function_definition`` / ``class_definition``
nodes around a syntax error, enabling partial symbol extraction from malformed
files where Python's ``ast`` would raise.
"""

from __future__ import annotations

from functools import lru_cache

import tree_sitter_javascript
import tree_sitter_python
import tree_sitter_typescript
from tree_sitter import Language, Node, Parser


@lru_cache(maxsize=1)
def python_language() -> Language:
    return Language(tree_sitter_python.language())


@lru_cache(maxsize=1)
def python_parser() -> Parser:
    return Parser(python_language())


@lru_cache(maxsize=1)
def javascript_parser() -> Parser:
    return Parser(Language(tree_sitter_javascript.language()))


@lru_cache(maxsize=1)
def typescript_parser() -> Parser:
    return Parser(Language(tree_sitter_typescript.language_typescript()))


@lru_cache(maxsize=1)
def tsx_parser() -> Parser:
    return Parser(Language(tree_sitter_typescript.language_tsx()))


def parse_python(source: bytes) -> Node:
    """Parse Python source and return the root node (never raises on syntax errors)."""
    return python_parser().parse(source).root_node


def node_has_error(root: Node) -> bool:
    """Whether the parse tree contains any ERROR or missing nodes."""
    return root.has_error

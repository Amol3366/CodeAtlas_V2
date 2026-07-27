"""Statement-level body classification for changed symbols.

A modified symbol's body is diffed line-wise with ``difflib`` and changed lines
are mapped to statements. The classification is syntax-level and labeled
``high_confidence_heuristic``: it does not claim runtime effect.
"""

from __future__ import annotations

import ast
import difflib
from collections.abc import Iterator
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from codeatlas.domain.change import BodyChangeClass

if TYPE_CHECKING:
    from tree_sitter import Node


class _StatementType(StrEnum):
    RETURN = "return"
    RAISE = "raise"
    THROW = "throw"
    CONSTRUCTOR = "constructor"
    OTHER = "other"


@dataclass(frozen=True)
class _Statement:
    type: _StatementType
    start_line: int
    end_line: int
    is_new: bool
    is_constructor: bool = False


def classify_body_change(
    base_content: bytes,
    target_content: bytes,
    language: str,
    base_range: tuple[int, int],
    target_range: tuple[int, int],
    *,
    is_route_adjacent: bool = False,
) -> BodyChangeClass:
    """Classify what kind of statement-level change occurred in a body.

    If ``is_route_adjacent`` is true, the result is always
    :attr:`BodyChangeClass.PUBLIC_CONTRACT_CHANGED`, because a route-adjacent
    body change is treated as a public contract change regardless of which
    statements changed.
    """
    if is_route_adjacent:
        return BodyChangeClass.PUBLIC_CONTRACT_CHANGED

    base_text = _decode(base_content)
    target_text = _decode(target_content)

    changed_lines = _changed_line_numbers(
        base_text,
        target_text,
        base_range,
        target_range,
    )
    if not changed_lines:
        return BodyChangeClass.NONE

    if language == "python":
        statements = _python_statements(target_text, target_range)
        base_statements = _python_statements(base_text, base_range)
    elif language in {"typescript", "javascript", "ts", "js"}:
        statements = _tsjs_statements(target_text, target_range)
        base_statements = _tsjs_statements(base_text, base_range)
    else:
        return BodyChangeClass.PUBLIC_BEHAVIOR_CHANGED

    classes: set[BodyChangeClass] = set()
    for line in changed_lines:
        if _inside_constructor(statements, line):
            classes.add(BodyChangeClass.STATE_INITIALIZATION_CHANGED)
            continue

        stmt = _innermost_statement(statements, line)
        if stmt is None:
            continue
        base_stmt = _find_matching_statement(base_statements, stmt)
        is_modified = base_stmt is not None
        if stmt.type is _StatementType.RETURN:
            if is_modified:
                classes.add(BodyChangeClass.RETURN_VALUE_CHANGED)
            else:
                classes.add(BodyChangeClass.PUBLIC_BEHAVIOR_CHANGED)
        elif stmt.type in {_StatementType.RAISE, _StatementType.THROW}:
            if is_modified:
                classes.add(BodyChangeClass.ERROR_BEHAVIOR_CHANGED)
            else:
                classes.add(BodyChangeClass.PUBLIC_BEHAVIOR_CHANGED)
        elif stmt.is_constructor:
            classes.add(BodyChangeClass.STATE_INITIALIZATION_CHANGED)
        else:
            classes.add(BodyChangeClass.PUBLIC_BEHAVIOR_CHANGED)

    if BodyChangeClass.RETURN_VALUE_CHANGED in classes:
        return BodyChangeClass.RETURN_VALUE_CHANGED
    if BodyChangeClass.ERROR_BEHAVIOR_CHANGED in classes:
        return BodyChangeClass.ERROR_BEHAVIOR_CHANGED
    if BodyChangeClass.STATE_INITIALIZATION_CHANGED in classes:
        return BodyChangeClass.STATE_INITIALIZATION_CHANGED
    return BodyChangeClass.PUBLIC_BEHAVIOR_CHANGED


def _decode(content: bytes) -> str:
    try:
        return content.decode("utf-8-sig")
    except UnicodeDecodeError:
        return content.decode("utf-8", errors="replace")


def _changed_line_numbers(
    base_text: str,
    target_text: str,
    base_range: tuple[int, int],
    target_range: tuple[int, int],
) -> tuple[int, ...]:
    base_lines = base_text.splitlines()
    target_lines = target_text.splitlines()

    base_slice = base_lines[base_range[0] - 1 : base_range[1]]
    target_slice = target_lines[target_range[0] - 1 : target_range[1]]

    matcher = difflib.SequenceMatcher(a=base_slice, b=target_slice, autojunk=False)
    changed: set[int] = set()
    for tag, _i1, _i2, j1, j2 in matcher.get_opcodes():
        if tag in {"replace", "insert", "delete"}:
            for index in range(j1, j2):
                changed.add(target_range[0] + index)

    return tuple(sorted(changed))


def _python_statements(
    text: str,
    line_range: tuple[int, int],
) -> tuple[_Statement, ...]:
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return ()

    statements: list[_Statement] = []
    for node in ast.walk(tree):
        if not hasattr(node, "lineno"):
            continue
        start = node.lineno
        end = getattr(node, "end_lineno", start)
        if end < start:
            end = start
        if start < line_range[0] or end > line_range[1]:
            continue

        stmt_type = _python_statement_type(node)
        is_constructor = isinstance(node, ast.FunctionDef) and _is_constructor(node)
        statements.append(
            _Statement(
                type=stmt_type,
                start_line=start,
                end_line=end,
                is_new=True,
                is_constructor=is_constructor,
            )
        )

    return tuple(sorted(statements, key=lambda s: (s.start_line, s.end_line)))


def _python_statement_type(node: ast.AST) -> _StatementType:
    if isinstance(node, ast.Return):
        return _StatementType.RETURN
    if isinstance(node, ast.Raise):
        return _StatementType.RAISE
    if isinstance(node, ast.FunctionDef) and _is_constructor(node):
        return _StatementType.CONSTRUCTOR
    return _StatementType.OTHER


def _is_constructor(node: ast.FunctionDef) -> bool:
    return node.name == "__init__"


def _tsjs_statements(text: str, line_range: tuple[int, int]) -> tuple[_Statement, ...]:
    try:
        from tree_sitter import Language, Parser
        from tree_sitter_typescript import language_tsx

        parser = Parser(Language(language_tsx()))
        tree = parser.parse(text.encode("utf-8"))
    except Exception:
        return ()

    statements: list[_Statement] = []
    root = tree.root_node
    for node in _walk_tree_sitter(root):
        start = node.start_point[0] + 1
        end = node.end_point[0] + 1
        if start < line_range[0] or end > line_range[1]:
            continue

        stmt_type = _tsjs_statement_type(node)
        is_constructor = (
            node.type == "method_definition"
            and any(
                child.type == "property_identifier" and child.text == b"constructor"
                for child in node.children
            )
        )
        statements.append(
            _Statement(
                type=stmt_type,
                start_line=start,
                end_line=end,
                is_new=True,
                is_constructor=is_constructor,
            )
        )

    return tuple(sorted(statements, key=lambda s: (s.start_line, s.end_line)))


def _walk_tree_sitter(node: Node) -> Iterator[Node]:
    yield node
    for child in node.children:
        yield from _walk_tree_sitter(child)


def _tsjs_statement_type(node: Node) -> _StatementType:
    if node.type == "return_statement":
        return _StatementType.RETURN
    if node.type == "throw_statement":
        return _StatementType.THROW
    if node.type == "method_definition" and any(
        child.type == "property_identifier" and child.text == b"constructor"
        for child in node.children
    ):
        return _StatementType.CONSTRUCTOR
    return _StatementType.OTHER


def _inside_constructor(statements: tuple[_Statement, ...], line: int) -> bool:
    return any(
        statement.is_constructor
        and statement.start_line <= line <= statement.end_line
        for statement in statements
    )


def _innermost_statement(
    statements: tuple[_Statement, ...], line: int
) -> _Statement | None:
    candidates = [s for s in statements if s.start_line <= line <= s.end_line]
    if not candidates:
        return None
    candidates.sort(key=lambda s: (s.end_line - s.start_line, s.start_line))
    return candidates[0]


def _find_matching_statement(
    base_statements: tuple[_Statement, ...],
    target_statement: _Statement,
) -> _Statement | None:
    for base in base_statements:
        if (
            base.type == target_statement.type
            and abs(base.start_line - target_statement.start_line) <= 2
        ):
            return base
    return None

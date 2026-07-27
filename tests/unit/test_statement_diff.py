"""Unit tests for statement-level body classification."""

from __future__ import annotations

from codeatlas.analysis.statement_diff import classify_body, classify_body_change
from codeatlas.domain.change import BodyChangeClass


def _contents(source: str) -> bytes:
    return source.encode("utf-8")


def test_unchanged_body_returns_none() -> None:
    source = "def capture() -> str:\n    return 'ok'\n"
    result = classify_body_change(
        _contents(source),
        _contents(source),
        "python",
        (1, 2),
        (1, 2),
    )
    assert result is BodyChangeClass.NONE


def test_modified_return_value() -> None:
    base = "def capture() -> str:\n    return 'ok'\n"
    target = "def capture() -> str:\n    return 'changed'\n"
    result = classify_body_change(
        _contents(base),
        _contents(target),
        "python",
        (1, 2),
        (1, 2),
    )
    assert result is BodyChangeClass.RETURN_VALUE_CHANGED


def test_modified_raise_is_error_behavior_change() -> None:
    base = "def validate(key: str) -> None:\n    raise ValueError('old')\n"
    target = "def validate(key: str) -> None:\n    raise ValueError('new')\n"
    result = classify_body_change(
        _contents(base),
        _contents(target),
        "python",
        (1, 2),
        (1, 2),
    )
    assert result is BodyChangeClass.ERROR_BEHAVIOR_CHANGED


def test_added_raise_is_ordinary_behavior_change() -> None:
    base = "def validate(key: str) -> None:\n    pass\n"
    target = (
        "def validate(key: str) -> None:\n"
        "    if not key:\n"
        "        raise ValueError('empty')\n"
    )
    result = classify_body_change(
        _contents(base),
        _contents(target),
        "python",
        (1, 2),
        (1, 4),
    )
    assert result is BodyChangeClass.PUBLIC_BEHAVIOR_CHANGED


def test_constructor_body_change_is_state_initialization() -> None:
    base = "class Service:\n    def __init__(self) -> None:\n        self.x = 1\n"
    target = "class Service:\n    def __init__(self) -> None:\n        self.x = 2\n"
    result = classify_body_change(
        _contents(base),
        _contents(target),
        "python",
        (2, 3),
        (2, 3),
    )
    assert result is BodyChangeClass.STATE_INITIALIZATION_CHANGED


def test_generic_public_body_change() -> None:
    base = "def capture() -> str:\n    x = 1\n    return 'ok'\n"
    target = "def capture() -> str:\n    x = 2\n    return 'ok'\n"
    result = classify_body_change(
        _contents(base),
        _contents(target),
        "python",
        (1, 3),
        (1, 3),
    )
    assert result is BodyChangeClass.PUBLIC_BEHAVIOR_CHANGED


def test_route_adjacent_override() -> None:
    base = "def handler() -> str:\n    return 'ok'\n"
    target = "def handler() -> str:\n    return 'changed'\n"
    result = classify_body_change(
        _contents(base),
        _contents(target),
        "python",
        (1, 2),
        (1, 2),
        is_route_adjacent=True,
    )
    assert result is BodyChangeClass.PUBLIC_CONTRACT_CHANGED


def test_unknown_language_defaults_to_public_behavior() -> None:
    base = "func foo() {}\n"
    target = "func foo() { changed }\n"
    result = classify_body_change(
        _contents(base),
        _contents(target),
        "go",
        (1, 1),
        (1, 1),
    )
    assert result is BodyChangeClass.PUBLIC_BEHAVIOR_CHANGED


def test_typescript_modified_return() -> None:
    base = "function total(): number {\n    return 1;\n}\n"
    target = "function total(): number {\n    return 2;\n}\n"
    result = classify_body_change(
        _contents(base),
        _contents(target),
        "typescript",
        (1, 3),
        (1, 3),
    )
    assert result is BodyChangeClass.RETURN_VALUE_CHANGED


def test_typescript_modified_throw_is_error_behavior() -> None:
    base = "function validate(): void {\n    throw new Error('old');\n}\n"
    target = "function validate(): void {\n    throw new Error('new');\n}\n"
    result = classify_body_change(
        _contents(base),
        _contents(target),
        "typescript",
        (1, 3),
        (1, 3),
    )
    assert result is BodyChangeClass.ERROR_BEHAVIOR_CHANGED


# --- Deletions and evidence spans (P4-10 corpus corrections) ---


def test_pure_statement_deletion_is_a_body_change() -> None:
    """c017: deleting a statement changes the body even though no target-side
    line differs. Silence here read exactly like an unchanged function."""
    base = 'def health() -> str:\n    checked = "ok"\n    return "ok"\n'
    target = 'def health() -> str:\n    return "ok"\n'
    result = classify_body_change(
        _contents(base),
        _contents(target),
        "python",
        (1, 3),
        (1, 2),
    )
    assert result is BodyChangeClass.PUBLIC_BEHAVIOR_CHANGED


def test_modified_return_span_covers_the_statements_it_reads() -> None:
    """c002: the changed return cites itself plus the statements that mention
    the names it uses - the reviewer needs the assignment feeding the return,
    and nothing above it."""
    base = (
        "def capture(key: str) -> str:\n"
        "    if not key:\n"
        '        raise ValueError("key is required")\n'
        "    token = claim(key)\n"
        '    return f"token={token}"\n'
    )
    target = (
        "def capture(key: str) -> str:\n"
        "    if not key:\n"
        '        raise ValueError("key is required")\n'
        "    token = claim(key)\n"
        '    return f"captured:{token}"\n'
    )
    result = classify_body(
        _contents(base),
        _contents(target),
        "python",
        (1, 5),
        (1, 5),
    )
    assert result.body_class is BodyChangeClass.RETURN_VALUE_CHANGED
    assert result.evidence_span == (4, 5)


def test_modified_raise_span_covers_its_condition_and_data_flow() -> None:
    """c023: a raise modified inside a condition cites the enclosing statement
    and every body statement sharing its names."""
    base = (
        "def process(value: str, *, strict: bool = False) -> str:\n"
        "    result = value.strip()\n"
        "    if strict and not result:\n"
        '        raise ValueError("value is required")\n'
        "    return result\n"
    )
    target = (
        "def process(value: str, *, strict: bool = False) -> str:\n"
        "    result = value.strip()\n"
        "    if strict and not result:\n"
        '        raise ValueError("empty value is not allowed")\n'
        "    return result\n"
    )
    result = classify_body(
        _contents(base),
        _contents(target),
        "python",
        (1, 5),
        (1, 5),
    )
    assert result.body_class is BodyChangeClass.ERROR_BEHAVIOR_CHANGED
    assert result.evidence_span == (2, 5)


def test_typescript_spans_stay_whole_symbol() -> None:
    """The Python ast path is the precise one; TS/JS classification does not
    claim statement-level spans (c009 cites the whole symbol)."""
    base = "function total(): number {\n    return 1;\n}\n"
    target = "function total(): number {\n    return 2;\n}\n"
    result = classify_body(
        _contents(base),
        _contents(target),
        "typescript",
        (1, 3),
        (1, 3),
    )
    assert result.body_class is BodyChangeClass.RETURN_VALUE_CHANGED
    assert result.evidence_span is None

"""The parser reads repository code as data and never runs it."""

from __future__ import annotations

from pathlib import Path

from codeatlas.parsing.python_parser import PythonParser
from codeatlas.parsing.registry import ParseRequest


def _request(content: bytes, path: str = "src/evil.py") -> ParseRequest:
    return ParseRequest(
        repository_id="repo_1",
        snapshot_id="snap_1",
        file_id="file_1",
        relative_path=path,
        language="python",
        content=content,
    )


def test_parser_never_executes_module_level_code(tmp_path: Path) -> None:
    marker = tmp_path / "executed.txt"
    source = f"open(r'{marker}', 'w').write('x')\n".encode()
    PythonParser().parse(_request(source))
    assert marker.exists() is False


def test_parser_never_executes_import_side_effects(tmp_path: Path) -> None:
    marker = tmp_path / "imported.txt"
    source = (
        "import pathlib\n"
        f"pathlib.Path(r'{marker}').write_text('x')\n"
        "class Real:\n"
        "    pass\n"
    ).encode()
    result = PythonParser().parse(_request(source))
    assert marker.exists() is False
    assert any(symbol.qualified_name == "Real" for symbol in result.symbols)


def test_parser_module_contains_no_execution_primitives() -> None:
    from codeatlas.parsing import python_parser

    text = Path(python_parser.__file__).read_text(encoding="utf-8")
    for forbidden in (
        "exec(",
        "eval(",
        "importlib",
        "__import__",
        "runpy",
        "subprocess",
    ):
        assert forbidden not in text


def test_deeply_nested_source_does_not_crash_the_parser() -> None:
    source = ("x = " + "[" * 60 + "]" * 60 + "\n").encode()
    result = PythonParser().parse(_request(source))
    assert isinstance(result.success, bool)

"""Malformed-source handling: diagnostics, partial recovery, no crash (Blueprint §8.18)."""

from __future__ import annotations

from codeatlas.domain.enums import Language
from codeatlas.parsing.contracts import ParseRequest
from codeatlas.parsing.executor import parse_many
from codeatlas.parsing.python.parser import PythonParser

_MALFORMED = b"""
def broken(:
    return 1


class Widget:
    def render(self):
        return 2
"""

_VALID = b"def ok():\n    return 1\n"


def _request(path: str, content: bytes) -> ParseRequest:
    return ParseRequest("repo_x", path, Language.PYTHON, content)


def test_malformed_file_records_diagnostic_and_recovers_partial_symbols() -> None:
    result = PythonParser().parse(_request("broken.py", _MALFORMED))
    assert result.success is False
    assert result.diagnostics
    assert result.diagnostics[0].severity == "error"
    # Tree-sitter recovered at least the well-formed class/method after the error.
    recovered = {s.qualified_name for s in result.symbols}
    assert "Widget" in recovered or "Widget.render" in recovered
    # Recovered symbols are flagged as lower confidence.
    assert all(s.parser_confidence < 1.0 for s in result.symbols)


def test_malformed_file_does_not_raise() -> None:
    # Even total garbage returns a result rather than raising.
    result = PythonParser().parse(_request("garbage.py", b"@@@ ??? def :::"))
    assert result.success is False
    assert result.diagnostics


def test_batch_continues_past_malformed_file() -> None:
    results = parse_many(
        [_request("bad.py", _MALFORMED), _request("good.py", _VALID)],
        use_processes=False,
    )
    by_path = {r.relative_path: r for r in results}
    assert by_path["bad.py"].success is False
    assert by_path["good.py"].success is True
    assert any(s.qualified_name == "ok" for s in by_path["good.py"].symbols)

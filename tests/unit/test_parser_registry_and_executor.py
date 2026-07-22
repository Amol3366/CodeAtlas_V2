"""Parser registry dispatch + bounded-concurrency executor (Blueprint §4.4.1, §4.10)."""

from __future__ import annotations

from pathlib import Path

from codeatlas.domain.enums import Language
from codeatlas.parsing.contracts import ParseRequest
from codeatlas.parsing.executor import _bounded_workers, parse_many, parse_request
from codeatlas.parsing.python.parser import PythonParser
from codeatlas.parsing.registry import default_registry

FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "python_repo"
_PY_FILES = [
    "src/services/payment_service.py",
    "src/payments/gateway.py",
    "src/payments/idempotency.py",
]


def _requests() -> list[ParseRequest]:
    return [
        ParseRequest("repo_x", rel, Language.PYTHON, (FIXTURE_ROOT / rel).read_bytes())
        for rel in _PY_FILES
    ]


def test_registry_dispatches_python_by_extension() -> None:
    registry = default_registry()
    assert isinstance(registry.for_path("src/a.py"), PythonParser)
    assert isinstance(registry.for_extension(".pyi"), PythonParser)
    assert registry.for_path("src/a.rs") is None


def test_bounded_workers_never_exceeds_ceiling() -> None:
    assert _bounded_workers(100, 4) == 4
    assert _bounded_workers(2, 4) == 2  # never more workers than items
    assert _bounded_workers(100, 999) <= 8  # global cap
    assert _bounded_workers(100, None) >= 1


def test_parse_request_dispatches_unknown_language_to_diagnostic() -> None:
    result = parse_request(ParseRequest("repo_x", "notes.rs", Language.PYTHON, b"fn main(){}"))
    assert result.success is False
    assert result.diagnostics


def test_parse_many_with_process_pool() -> None:
    results = parse_many(_requests(), use_processes=True, max_workers=2)
    assert len(results) == len(_PY_FILES)
    assert all(r.success for r in results)
    # Determinism across the pool boundary: same ids as inline parsing.
    inline = parse_many(_requests(), use_processes=False)
    pooled_ids = [tuple(s.id for s in r.symbols) for r in results]
    inline_ids = [tuple(s.id for s in r.symbols) for r in inline]
    assert pooled_ids == inline_ids

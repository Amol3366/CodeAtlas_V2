"""Bounded-concurrency parsing (Blueprint §4.10, CLAUDE.md §2.12).

CPU-bound parsing runs in a ``ProcessPoolExecutor`` with bounded worker count.
The worker entry point (:func:`parse_request`) is module-level and its
arguments/results are plain frozen dataclasses, so they pickle cleanly across
the Windows spawn boundary. A missing parser yields a diagnostic result rather
than raising.
"""

from __future__ import annotations

import os
from collections.abc import Iterable
from concurrent.futures import ProcessPoolExecutor

from codeatlas.parsing.contracts import ParseDiagnostic, ParseRequest, ParseResult
from codeatlas.parsing.registry import ParserRegistry, default_registry

_MAX_WORKERS = 8

# One registry per process (built lazily; cheap and cached for pool workers).
_REGISTRY: ParserRegistry | None = None


def _registry() -> ParserRegistry:
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = default_registry()
    return _REGISTRY


def parse_request(request: ParseRequest) -> ParseResult:
    """Parse a single request using the process-local registry."""
    parser = _registry().for_path(request.relative_path)
    if parser is None:
        return ParseResult(
            parser_name="none",
            parser_version="0",
            language=request.language,
            relative_path=request.relative_path,
            success=False,
            diagnostics=(
                ParseDiagnostic(
                    severity="warning",
                    message=f"No parser registered for {request.relative_path}",
                ),
            ),
        )
    return parser.parse(request)


def _bounded_workers(count: int, requested: int | None) -> int:
    ceiling = requested or (os.cpu_count() or 2)
    return max(1, min(ceiling, _MAX_WORKERS, count))


def parse_many(
    requests: Iterable[ParseRequest],
    *,
    max_workers: int | None = None,
    use_processes: bool = True,
) -> list[ParseResult]:
    """Parse many requests. Uses a process pool for >1 request unless disabled."""
    items = list(requests)
    if not items:
        return []
    if not use_processes or len(items) == 1:
        return [parse_request(item) for item in items]

    workers = _bounded_workers(len(items), max_workers)
    with ProcessPoolExecutor(max_workers=workers) as executor:
        return list(executor.map(parse_request, items))

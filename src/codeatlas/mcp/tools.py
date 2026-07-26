"""Versioned MCP tool definitions over the shared application services.

Two rules shape this module.

**No tool duplicates repository logic.** Each one validates a bounded input
model and calls exactly one application service. If a tool needed logic of its
own, that logic would belong in the application layer where the REST and CLI
adapters could reach it too.

**An absent tool beats an unimplemented one.** `analyze_change` is deliberately
not registered in Phase 3: an agent that sees a tool will call it, and a tool
that answers "unimplemented" wastes a turn and teaches the agent nothing. It
arrives in Phase 4 with an implementation behind it.

Inputs are bounded at the boundary — query length, result count, traversal depth
— so an out-of-range request is refused before it reaches a service.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from codeatlas.application.container import ApplicationServices
from codeatlas.application.graph_queries import GraphQueryRequest
from codeatlas.application.lookup import MAX_RESULTS, SymbolLookupRequest
from codeatlas.application.registration import RegisterRepositoryRequest
from codeatlas.contracts import ErrorDetail, ErrorEnvelope
from codeatlas.domain.errors import CodeAtlasError
from codeatlas.retrieval.graph import MAX_ALLOWED_DEPTH, TraversalLimits
from codeatlas.retrieval.lexical import MAX_SEARCH_RESULTS, SearchRequest

# Bumped whenever a tool's input or output shape changes, so a client can detect
# a change rather than discover it through a malformed response.
TOOL_SCHEMA_VERSION = "1.0"

MAX_TEXT_LENGTH = 512


class ToolInput(BaseModel):
    """Base for every tool input: unknown fields are refused, not ignored."""

    model_config = ConfigDict(extra="forbid")


class RepositoryPathInput(ToolInput):
    path: str = Field(min_length=1, max_length=4096)
    display_name: str | None = Field(default=None, max_length=256)


class RepositoryInput(ToolInput):
    repository_id: str = Field(min_length=1, max_length=256)


class EmptyInput(ToolInput):
    pass


class SymbolInput(RepositoryInput):
    symbol: str = Field(min_length=1, max_length=MAX_TEXT_LENGTH)
    max_results: int = Field(default=MAX_RESULTS, ge=1, le=MAX_RESULTS)


class SearchInput(RepositoryInput):
    query: str = Field(min_length=1, max_length=MAX_TEXT_LENGTH)
    limit: int = Field(default=MAX_SEARCH_RESULTS, ge=1, le=MAX_SEARCH_RESULTS)


class GraphInput(RepositoryInput):
    symbol: str = Field(min_length=1, max_length=MAX_TEXT_LENGTH)
    depth: int = Field(default=2, ge=1, le=MAX_ALLOWED_DEPTH)


class EvidenceInput(RepositoryInput):
    evidence_id: str = Field(min_length=1, max_length=256)


class FileInput(RepositoryInput):
    file_id: str = Field(min_length=1, max_length=256)


@dataclass(frozen=True)
class Tool:
    """One registered tool: a bounded input model and a handler."""

    name: str
    description: str
    input_model: type[ToolInput]
    handler: Callable[[ApplicationServices, ToolInput], Any]

    def schema(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "schema_version": TOOL_SCHEMA_VERSION,
            "input_schema": self.input_model.model_json_schema(),
        }


class ToolRegistry:
    """The tools this adapter exposes, and how to call them."""

    def __init__(self, tools: Mapping[str, Tool]) -> None:
        self._tools = dict(tools)

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._tools))

    def schemas(self) -> list[dict[str, Any]]:
        return [self._tools[name].schema() for name in self.names]

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def call(
        self, services: ApplicationServices, name: str, arguments: Mapping[str, Any]
    ) -> Any:
        """Validate, dispatch, and translate failures into the error envelope."""
        tool = self._tools.get(name)
        if tool is None:
            return _envelope("INVALID_REQUEST", f"No such tool: {name}.")

        try:
            payload = tool.input_model.model_validate(dict(arguments))
        except ValueError as error:
            # Bounds are part of the contract, so a violation is a client error
            # with a stable shape — never a stack trace.
            return _envelope("INVALID_REQUEST", _first_message(error))

        try:
            return tool.handler(services, payload)
        except CodeAtlasError as error:
            return _envelope(error.code.value, error.message, error.retryable)


def build_registry() -> ToolRegistry:
    """Build the Phase 3 tool set.

    `analyze_change` is absent by design; see the module docstring.
    """
    tools = [
        Tool(
            name="register_repository",
            description="Register a local repository for indexing.",
            input_model=RepositoryPathInput,
            handler=_register_repository,
        ),
        Tool(
            name="list_repositories",
            description="List registered repositories.",
            input_model=EmptyInput,
            handler=lambda services, _: [
                {
                    "repository_id": item.repository_id,
                    "display_name": item.display_name,
                }
                for item in services.registration.list_all()
            ],
        ),
        Tool(
            name="get_repository",
            description="Get one registered repository.",
            input_model=RepositoryInput,
            handler=lambda services, payload: _repository(services, payload),
        ),
        Tool(
            name="get_status",
            description="Get indexing and freshness status.",
            input_model=RepositoryInput,
            handler=lambda services, payload: _status(services, payload),
        ),
        Tool(
            name="get_diagnostics",
            description="Get exclusions, limits, and parse errors.",
            input_model=RepositoryInput,
            handler=lambda services, payload: _diagnostics(services, payload),
        ),
        Tool(
            name="resolve_symbol",
            description="Resolve an exact symbol to verified evidence.",
            input_model=SymbolInput,
            handler=_resolve_symbol,
        ),
        Tool(
            name="search_files",
            description="Search file paths lexically.",
            input_model=SearchInput,
            handler=lambda services, payload: services.search.search_files(
                _search_request(payload)
            ),
        ),
        Tool(
            name="search_symbols",
            description="Search symbol names, exact resolution first.",
            input_model=SearchInput,
            handler=lambda services, payload: services.search.search_symbols(
                _search_request(payload)
            ),
        ),
        Tool(
            name="search_text",
            description="Search indexed chunk text.",
            input_model=SearchInput,
            handler=lambda services, payload: services.search.search_text(
                _search_request(payload)
            ),
        ),
        Tool(
            name="get_evidence",
            description="Re-read and re-verify one cited region.",
            input_model=EvidenceInput,
            handler=_get_evidence,
        ),
        Tool(
            name="resolve_file",
            description="Get one file of the active snapshot by ID.",
            input_model=FileInput,
            handler=_resolve_file,
        ),
        *(
            Tool(
                name=name,
                description=description,
                input_model=GraphInput,
                handler=_graph_handler(view),
            )
            for name, view, description in (
                ("get_callers", "callers", "List the symbols that call this one."),
                ("get_callees", "callees", "List the symbols this one calls."),
                (
                    "get_dependencies",
                    "dependencies",
                    "List what this symbol imports or references.",
                ),
                ("get_exports", "exports", "List what a module exports."),
                (
                    "get_related_tests",
                    "tests",
                    "List the tests that exercise this symbol.",
                ),
                (
                    "get_related_documents",
                    "documents",
                    "List documents that mention this symbol (advisory only).",
                ),
                ("trace_flow", "trace", "Trace bounded relation paths."),
            )
        ),
    ]
    return ToolRegistry({tool.name: tool for tool in tools})


def _register_repository(services: ApplicationServices, payload: ToolInput) -> Any:
    assert isinstance(payload, RepositoryPathInput)
    repository = services.registration.register(
        RegisterRepositoryRequest(
            path=payload.path, display_name=payload.display_name
        )
    )
    return {
        "repository_id": repository.repository_id,
        "display_name": repository.display_name,
    }


def _repository(services: ApplicationServices, payload: ToolInput) -> Any:
    assert isinstance(payload, RepositoryInput)
    repository = services.registration.get(payload.repository_id)
    return {
        "repository_id": repository.repository_id,
        "display_name": repository.display_name,
    }


def _status(services: ApplicationServices, payload: ToolInput) -> Any:
    assert isinstance(payload, RepositoryInput)
    result = services.status.status(payload.repository_id)
    return {
        "repository_id": payload.repository_id,
        "snapshot_id": result.snapshot.snapshot_id if result.snapshot else None,
        # A repository with no snapshot reports "none" rather than omitting the
        # field, so a client can tell "not indexed" from "field missing".
        "state": "active" if result.snapshot else "none",
        "freshness": (
            result.snapshot.freshness.value if result.snapshot else "unknown"
        ),
        "file_count": result.file_count,
        "symbol_count": result.symbol_count,
        "parse_error_count": result.parse_error_count,
        "warnings": list(result.warnings),
    }


def _diagnostics(services: ApplicationServices, payload: ToolInput) -> Any:
    assert isinstance(payload, RepositoryInput)
    report = services.status.diagnostics(payload.repository_id)
    return {
        "repository_id": report.repository_id,
        "snapshot_id": report.snapshot_id,
        "skipped_by_reason": dict(report.skipped_by_reason),
        "parse_error_count": report.parse_error_count,
        "warnings": list(report.warnings),
    }


def _resolve_symbol(services: ApplicationServices, payload: ToolInput) -> Any:
    assert isinstance(payload, SymbolInput)
    return services.lookup.lookup(
        SymbolLookupRequest(
            repository_id=payload.repository_id,
            query=payload.symbol,
            request_id=_request_id(),
            max_results=payload.max_results,
        )
    )


def _get_evidence(services: ApplicationServices, payload: ToolInput) -> Any:
    assert isinstance(payload, EvidenceInput)
    return services.entities.get_evidence(
        payload.repository_id, payload.evidence_id
    )


def _resolve_file(services: ApplicationServices, payload: ToolInput) -> Any:
    assert isinstance(payload, FileInput)
    detail = services.entities.get_file(payload.repository_id, payload.file_id)
    return {
        "snapshot_id": detail.snapshot.snapshot_id,
        "file_id": detail.file.file_id,
        "path": detail.file.relative_path,
        "language": detail.file.language,
        "line_count": detail.file.line_count,
    }


def _graph_handler(
    view: str,
) -> Callable[[ApplicationServices, ToolInput], Any]:
    def handler(services: ApplicationServices, payload: ToolInput) -> Any:
        assert isinstance(payload, GraphInput)
        request = GraphQueryRequest(
            repository_id=payload.repository_id,
            symbol=payload.symbol,
            request_id=_request_id(),
            max_depth=payload.depth,
            limits=TraversalLimits(max_depth=payload.depth),
        )
        return {
            "callers": services.graph.callers,
            "callees": services.graph.callees,
            "dependencies": services.graph.dependencies,
            "exports": services.graph.exports,
            "tests": services.graph.related_tests,
            "documents": services.graph.related_documents,
            "trace": services.graph.trace,
        }[view](request)

    return handler


def _search_request(payload: ToolInput) -> SearchRequest:
    assert isinstance(payload, SearchInput)
    return SearchRequest(
        repository_id=payload.repository_id,
        query=payload.query,
        request_id=_request_id(),
        limit=payload.limit,
    )


def _request_id() -> str:
    return f"mcp_{uuid.uuid4().hex}"


def _envelope(code: str, message: str, retryable: bool = False) -> ErrorEnvelope:
    return ErrorEnvelope(
        error=ErrorDetail(
            code=code,
            message=message,
            request_id=_request_id(),
            retryable=retryable,
            details={},
        )
    )


def _first_message(error: ValueError) -> str:
    """Summarize a validation failure without echoing the offending input.

    Repository content and user text are untrusted; a message that quotes them
    back becomes an injection surface in whatever renders it.
    """
    text = str(error).splitlines()
    return text[0] if text else "The tool input is invalid."

"""The stdio MCP server.

Stdio only. Nothing here opens a socket, binds a port, or accepts a connection,
so exposing CodeAtlas over MCP does not widen its network surface at all — the
client already has local process access by construction.

The server owns no repository logic: it lists tool schemas, dispatches a call to
:class:`ToolRegistry`, and serializes the result. Everything the tools return is
already a contract model or a plain mapping, so the MCP surface and the REST
surface cannot drift apart in what they claim.
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from codeatlas.application.container import ApplicationServices, build_services
from codeatlas.mcp.tools import TOOL_SCHEMA_VERSION, ToolRegistry, build_registry
from codeatlas.storage.sqlite.connection import connect, default_database_path
from codeatlas.storage.sqlite.migrations import apply_migrations

SERVER_NAME = "codeatlas"
SERVER_VERSION = "1.0"

# Bounded so a single tool result cannot exhaust a client's context window. A
# truncated payload says so rather than being silently cut.
MAX_RESULT_CHARACTERS = 200_000


@contextmanager
def open_services(database: Path | None = None) -> Iterator[ApplicationServices]:
    """Open the database, apply migrations, and build the services."""
    path = database or default_database_path()
    with connect(path) as connection:
        apply_migrations(connection)
        yield build_services(connection)


class McpServer:
    """A minimal, transport-agnostic MCP surface over the application services."""

    def __init__(
        self, services: ApplicationServices, registry: ToolRegistry | None = None
    ) -> None:
        self._services = services
        self._registry = registry or build_registry()

    def describe(self) -> dict[str, Any]:
        return {
            "name": SERVER_NAME,
            "version": SERVER_VERSION,
            "schema_version": TOOL_SCHEMA_VERSION,
            "tools": self._registry.schemas(),
        }

    def call_tool(self, name: str, arguments: Mapping[str, Any]) -> str:
        """Call one tool and serialize its result as bounded JSON text."""
        result = self._registry.call(self._services, name, arguments)
        return _serialize(result)


def _serialize(result: Any) -> str:
    if isinstance(result, BaseModel):
        text = result.model_dump_json()
    else:
        text = json.dumps(result, default=str)

    if len(text) > MAX_RESULT_CHARACTERS:
        return json.dumps(
            {
                "truncated": True,
                "reason": "RESULT_TOO_LARGE",
                "message": (
                    "The result exceeded the maximum tool response size and was"
                    " withheld. Narrow the query and try again."
                ),
            }
        )
    return text


def run_stdio(database: Path | None = None) -> None:  # pragma: no cover
    """Serve MCP over stdio.

    Imported lazily so the `mcp` package is only required when the server is
    actually started — the tool registry and its contract tests do not need it.
    """
    import anyio
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    from mcp.types import TextContent
    from mcp.types import Tool as McpTool

    with open_services(database) as services:
        surface = McpServer(services)
        server: Server[object, object] = Server(SERVER_NAME)

        @server.list_tools()
        async def list_tools() -> list[McpTool]:
            return [
                McpTool(
                    name=schema["name"],
                    description=schema["description"],
                    inputSchema=schema["input_schema"],
                )
                for schema in surface.describe()["tools"]
            ]

        @server.call_tool()
        async def call_tool(
            name: str, arguments: dict[str, Any]
        ) -> list[TextContent]:
            return [
                TextContent(type="text", text=surface.call_tool(name, arguments))
            ]

        async def main() -> None:
            async with stdio_server() as (read_stream, write_stream):
                await server.run(
                    read_stream,
                    write_stream,
                    server.create_initialization_options(),
                )

        anyio.run(main)


def main() -> None:  # pragma: no cover
    """Console-script entry point."""
    run_stdio()

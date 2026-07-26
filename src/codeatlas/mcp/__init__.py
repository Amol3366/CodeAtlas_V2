"""The MCP adapter.

MCP is a sibling of the REST and CLI adapters, not a reimplementation. Every
tool validates its input, calls one application service, and serializes the same
contract models the other adapters return — which is what lets the cross-adapter
contract suite assert that all three answer identically.

Transport is stdio only. No socket is opened and no port is bound, so
``CLAUDE.md`` Section 18's loopback-by-default requirement is unaffected.
"""

from codeatlas.mcp.tools import TOOL_SCHEMA_VERSION, ToolRegistry, build_registry

__all__ = ["TOOL_SCHEMA_VERSION", "ToolRegistry", "build_registry"]

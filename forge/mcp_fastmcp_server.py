"""The same Forge MCP tools on the official Python SDK (pip install "mcp").

Run over stdio:            python -m forge.mcp_fastmcp_server
Run over Streamable HTTP:  python -m forge.mcp_fastmcp_server --http   (http://127.0.0.1:8765/mcp)
"""
from __future__ import annotations

import sys

from mcp.server.fastmcp import FastMCP

from .mcp_server import ForgeMCP

core = ForgeMCP()
mcp = FastMCP("forge-mcp", host="127.0.0.1", port=8765)


@mcp.tool()
def list_open_bugs(module: str = "") -> str:
    """List open forgeapp bug reports (id, module, title)."""
    return core._call("list_open_bugs", {"module": module})["content"][0]["text"]


@mcp.tool()
def lint_pipeline() -> str:
    """Validate the CI/CD pipeline and return violations."""
    return core._call("lint_pipeline", {})["content"][0]["text"]


@mcp.tool()
def search_runbooks(query: str, k: int = 3) -> str:
    """Hybrid search over runbooks and postmortems."""
    return core._call("search_runbooks", {"query": query, "k": k})["content"][0]["text"]


if __name__ == "__main__":
    mcp.run(transport="streamable-http" if "--http" in sys.argv else "stdio")

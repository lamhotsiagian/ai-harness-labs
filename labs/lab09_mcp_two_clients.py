"""Lab 9: publish an MCP server and call it from two clients (raw JSON-RPC and the official SDK)."""
from __future__ import annotations

import asyncio
import sys
import time

from labs.common import ROOT, LabReport, finish, lab_args
from forge.mcp_server import StdioMCPClient
from forge.tools import ToolRegistry, ToolSpec


def raw_client() -> dict:
    """Client 1: 40 lines of JSON-RPC over pipes. No SDK, nothing hidden."""
    t0 = time.time()
    c = StdioMCPClient([sys.executable, "-m", "forge.mcp_server"], cwd=ROOT)
    init = c.request("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                    "clientInfo": {"name": "forge-raw", "version": "1.0"}})
    c.notify("notifications/initialized")
    tools = [t["name"] for t in c.request("tools/list")["tools"]]
    hit = c.request("tools/call", {"name": "search_runbooks", "arguments": {"query": "429 for every client"}})
    resources = c.request("resources/list")["resources"]
    c.close()
    return {"client": "raw JSON-RPC", "server": init["serverInfo"]["name"], "tools": len(tools),
            "resources": len(resources), "top_hit": hit["content"][0]["text"].split('"id": "')[1][:6],
            "ms": int((time.time() - t0) * 1000)}


def sdk_client() -> dict:
    """Client 2: the official MCP Python SDK talking to the FastMCP build of the same tools."""
    try:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
    except ImportError:
        return {"client": "official SDK", "server": "skipped: pip install mcp", "tools": 0, "resources": 0,
                "top_hit": "-", "ms": 0}

    async def go() -> dict:
        t0 = time.time()
        params = StdioServerParameters(command=sys.executable, args=["-m", "forge.mcp_fastmcp_server"],
                                       cwd=str(ROOT))
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                info = await session.initialize()
                tools = (await session.list_tools()).tools
                res = await session.call_tool("search_runbooks", {"query": "429 for every client"})
                text = res.content[0].text
        return {"client": "official SDK", "server": info.serverInfo.name, "tools": len(tools), "resources": 0,
                "top_hit": text.split('"id": "')[1][:6], "ms": int((time.time() - t0) * 1000)}
    return asyncio.run(go())


def mcp_bridge_registry() -> tuple[ToolRegistry, StdioMCPClient]:
    """Mount every MCP tool into Forge's registry: the agent cannot tell local from remote."""
    client = StdioMCPClient([sys.executable, "-m", "forge.mcp_server"], cwd=ROOT)
    client.request("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                  "clientInfo": {"name": "forge-bridge", "version": "1.0"}})
    reg = ToolRegistry()
    for t in client.request("tools/list")["tools"]:
        def handler(_name=t["name"], **args):
            out = client.request("tools/call", {"name": _name, "arguments": args})
            return "\n".join(c.get("text", "") for c in out["content"])
        read_only = t.get("annotations", {}).get("readOnlyHint", False)
        reg.register(ToolSpec(f"mcp__forge__{t['name']}", t["description"], t["inputSchema"], handler,
                              side_effect="read" if read_only else "external"))
    return reg, client


def run(model: str = "sim:frontier", seeds: int = 1) -> LabReport:
    rows = [raw_client(), sdk_client()]
    reg, client = mcp_bridge_registry()
    bridged = reg.call("mcp__forge__lint_pipeline", {})
    client.close()
    return LabReport("09", "One MCP server, two clients", "The same server answers a hand-written JSON-RPC client "
                     "and the official SDK; a bridge mounts its tools into the Forge registry.",
                     {"bridged_tools": ", ".join(reg.names()), "bridged_call_ok": bridged.ok,
                      "bridged_result": bridged.content.replace("\n", " ")[:90]}, rows,
                     notes=["Inspect interactively: npx @modelcontextprotocol/inspector python -m forge.mcp_server"])


def main() -> None:
    a = lab_args(__doc__, seeds=1)
    finish(run(a.model, a.seeds), a.json)


if __name__ == "__main__":
    main()

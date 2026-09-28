"""A dependency-free MCP server for Forge over stdio (JSON-RPC 2.0, one message per line).

Implements the subset every client needs: initialize, tools/list, tools/call,
resources/list, resources/read, ping. It also accepts calls *without* a prior
initialize, matching the stateless direction of the 2026 specification, so it
runs behind a load balancer or a one-shot CLI equally well.

Run it:   python -m forge.mcp_server
Inspect:  npx @modelcontextprotocol/inspector python -m forge.mcp_server
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from .platform import lint, parse_pipeline
from .retrieval import HybridRetriever, load_corpus
from .tasks import SAMPLE_REPO, load_bugs

PROTOCOL_VERSION = "2025-06-18"
SERVER_INFO = {"name": "forge-mcp", "version": "1.0.0"}

TOOLS = [
    {"name": "list_open_bugs", "description": "List open forgeapp bug reports (id, module, title).",
     "inputSchema": {"type": "object", "properties": {"module": {"type": "string"}}},
     "annotations": {"readOnlyHint": True}},
    {"name": "read_repo_file", "description": "Read a file from the forgeapp repository (read-only).",
     "inputSchema": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
     "annotations": {"readOnlyHint": True}},
    {"name": "lint_pipeline", "description": "Validate the CI/CD pipeline and return violations.",
     "inputSchema": {"type": "object", "properties": {}}, "annotations": {"readOnlyHint": True}},
    {"name": "search_runbooks", "description": "Hybrid search over runbooks and postmortems; returns ids and first lines.",
     "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}, "k": {"type": "integer"}},
                     "required": ["query"]}, "annotations": {"readOnlyHint": True}},
]


class ForgeMCP:
    def __init__(self) -> None:
        self.docs = load_corpus()
        self.retriever = HybridRetriever(self.docs)

    # ------------------------------------------------------------- dispatch
    def handle(self, msg: dict) -> dict | None:
        method, mid = msg.get("method"), msg.get("id")
        if mid is None:                       # notification (e.g. notifications/initialized)
            return None
        try:
            result = self._route(method, msg.get("params") or {})
            return {"jsonrpc": "2.0", "id": mid, "result": result}
        except KeyError as exc:
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"unknown method {exc}"}}
        except Exception as exc:
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32603, "message": str(exc)}}

    def _route(self, method: str, params: dict) -> Any:
        if method == "initialize":
            return {"protocolVersion": PROTOCOL_VERSION, "serverInfo": SERVER_INFO,
                    "capabilities": {"tools": {"listChanged": False}, "resources": {}}}
        if method == "ping":
            return {}
        if method == "tools/list":
            return {"tools": TOOLS}
        if method == "tools/call":
            return self._call(params["name"], params.get("arguments") or {})
        if method == "resources/list":
            return {"resources": [{"uri": f"forge://docs/{d.id}", "name": d.id, "mimeType": "text/markdown"}
                                  for d in self.docs]}
        if method == "resources/read":
            doc_id = params["uri"].rsplit("/", 1)[-1]
            doc = next(d for d in self.docs if d.id == doc_id)
            return {"contents": [{"uri": params["uri"], "mimeType": "text/markdown", "text": doc.text}]}
        raise KeyError(method)

    def _call(self, name: str, args: dict) -> dict:
        def ok(payload: Any) -> dict:
            text = payload if isinstance(payload, str) else json.dumps(payload, indent=1)
            out = {"content": [{"type": "text", "text": text}], "isError": False}
            if not isinstance(payload, str):
                out["structuredContent"] = {"result": payload}
            return out

        if name == "list_open_bugs":
            bugs = [{"id": b["id"], "module": b["module"], "title": b["title"]} for b in load_bugs()
                    if not args.get("module") or b["module"] == args["module"]]
            return ok(bugs)
        if name == "read_repo_file":
            target = (SAMPLE_REPO / args["path"]).resolve()
            if SAMPLE_REPO.resolve() not in target.parents or not target.is_file():
                return {"content": [{"type": "text", "text": "path outside repository or missing"}], "isError": True}
            return ok(target.read_text())
        if name == "lint_pipeline":
            doc = parse_pipeline((SAMPLE_REPO / ".forge" / "pipeline.yaml").read_text())
            return ok({"violations": lint(doc), "stages": [s["name"] for s in doc["stages"]]})
        if name == "search_runbooks":
            hits = self.retriever.search(args["query"], int(args.get("k", 3)))
            return ok([{"id": d.id, "first_line": d.text.splitlines()[0]} for d in hits])
        return {"content": [{"type": "text", "text": f"unknown tool {name}"}], "isError": True}


def serve_stdio() -> None:
    server = ForgeMCP()
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        reply = server.handle(json.loads(line))
        if reply is not None:
            sys.stdout.write(json.dumps(reply) + "\n")
            sys.stdout.flush()


class StdioMCPClient:
    """Minimal MCP client: spawns a server process and speaks JSON-RPC over pipes."""

    def __init__(self, command: list[str], cwd: Path | None = None):
        self.proc = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     text=True, cwd=cwd, bufsize=1)
        self._id = 0

    def request(self, method: str, params: dict | None = None) -> Any:
        self._id += 1
        self.proc.stdin.write(json.dumps({"jsonrpc": "2.0", "id": self._id, "method": method,
                                          "params": params or {}}) + "\n")
        self.proc.stdin.flush()
        reply = json.loads(self.proc.stdout.readline())
        if "error" in reply:
            raise RuntimeError(reply["error"]["message"])
        return reply["result"]

    def notify(self, method: str) -> None:
        self.proc.stdin.write(json.dumps({"jsonrpc": "2.0", "method": method}) + "\n")
        self.proc.stdin.flush()

    def close(self) -> None:
        self.proc.stdin.close()
        self.proc.wait(timeout=5)


if __name__ == "__main__":
    serve_stdio()

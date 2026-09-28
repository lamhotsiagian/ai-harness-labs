"""Forge's concrete tools, bound to one sandboxed workspace.

`style="good"` gives the production tool designs from Chapter 8.
`style="bad"` gives the three anti-patterns that Lab 8 measures:
unpaginated reads, errors without hints, and raw test dumps.
"""
from __future__ import annotations

import difflib
import fnmatch
import json
import shutil
import time
from pathlib import Path

from .config import HarnessConfig
from .sandbox import Sandbox
from .tasks import run_unittest
from .tools import ToolError, ToolRegistry, ToolSpec

WEB = Path(__file__).resolve().parent.parent / "fixtures" / "web"


def build_forge_tools(sandbox: Sandbox, config: HarnessConfig, style: str = "good") -> ToolRegistry:
    reg = ToolRegistry()
    root = sandbox.root
    page = config.read_page_size

    # ------------------------------------------------------------------ read
    def read_file(path: str, offset: int = 0) -> str:
        p = sandbox.resolve(path)
        if not p.is_file():
            raise ToolError(f"no such file '{path}'", "call list_files to see what exists")
        text = p.read_text(errors="replace")
        if style == "bad":
            return text                                  # whole file, no paging
        chunk = text[offset: offset + page]
        header = f"# {path} (chars {offset}-{offset + len(chunk)} of {len(text)})\n"
        more = ""
        if offset + page < len(text):
            more = f"\n[more: call read_file(path='{path}', offset={offset + page})]"
        return header + chunk + more

    reg.register(ToolSpec(
        "read_file", "Read a UTF-8 file from the repository. Large files are paged; "
        "follow the [more: ...] marker to continue.",
        {"type": "object", "properties": {"path": {"type": "string"},
                                          "offset": {"type": "integer", "minimum": 0}},
         "required": ["path"], "additionalProperties": False},
        read_file, max_result_chars=10**7 if style == "bad" else page + 400))

    def list_files(path: str = ".", pattern: str = "*") -> str:
        base = sandbox.resolve(path)
        out = [str(p.relative_to(root)) for p in sorted(base.rglob("*"))
               if p.is_file() and fnmatch.fnmatch(p.name, pattern)
               and ".forge/commits" not in str(p) and "__pycache__" not in str(p)]
        return "\n".join(out[:200]) + (f"\n[{len(out) - 200} more]" if len(out) > 200 else "")

    reg.register(ToolSpec(
        "list_files", "List repository files under a directory, optionally filtered by a glob.",
        {"type": "object", "properties": {"path": {"type": "string"}, "pattern": {"type": "string"}},
         "additionalProperties": False}, list_files))

    def search_code(pattern: str, path: str = ".") -> str:
        base = sandbox.resolve(path)
        hits = []
        for p in sorted(base.rglob("*.py")):
            for i, line in enumerate(p.read_text(errors="replace").splitlines(), 1):
                if pattern.lower() in line.lower():
                    hits.append(f"{p.relative_to(root)}:{i}: {line.strip()}")
        if not hits:
            return f"no matches for '{pattern}'"
        return "\n".join(hits[:50]) + (f"\n[{len(hits) - 50} more matches; refine the pattern]"
                                       if len(hits) > 50 else "")

    reg.register(ToolSpec(
        "search_code", "Case-insensitive substring search over Python files; returns file:line: text.",
        {"type": "object", "properties": {"pattern": {"type": "string"}, "path": {"type": "string"}},
         "required": ["pattern"], "additionalProperties": False}, search_code))

    # ----------------------------------------------------------------- write
    def edit_file(path: str, find: str, replace: str) -> str:
        p = sandbox.resolve(path, for_write=True)
        if config.protect_tests and path.startswith("tests/"):
            raise ToolError("edits under tests/ are blocked by policy",
                            "fix the implementation instead of the test")
        text = p.read_text()
        count = text.count(find)
        if count == 0:
            if style == "bad":
                raise ToolError("edit failed")
            lines = text.splitlines()
            close = difflib.get_close_matches(find.strip(), [l.strip() for l in lines], n=1, cutoff=0.3)
            where = f" closest line: {close[0]!r}" if close else ""
            raise ToolError("find text not found in " + path,
                            f"re-read the file; the text may have changed.{where}")
        if count > 1:
            raise ToolError(f"find text matches {count} places",
                            "include more surrounding context so the match is unique")
        p.write_text(text.replace(find, replace, 1))
        return f"edited {path}: replaced 1 occurrence ({len(find)} -> {len(replace)} chars)"

    reg.register(ToolSpec(
        "edit_file", "Replace exactly one occurrence of `find` with `replace` in a file.",
        {"type": "object", "properties": {"path": {"type": "string"}, "find": {"type": "string"},
                                          "replace": {"type": "string"}},
         "required": ["path", "find", "replace"], "additionalProperties": False},
        edit_file, side_effect="write", idempotent=False))

    def write_file(path: str, content: str) -> str:
        p = sandbox.resolve(path, for_write=True)
        if config.protect_tests and path.startswith("tests/"):
            raise ToolError("writes under tests/ are blocked by policy",
                            "fix the implementation instead of the test")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
        return f"wrote {len(content)} chars to {path}"

    reg.register(ToolSpec(
        "write_file", "Create or overwrite a file with the given content.",
        {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
         "required": ["path", "content"], "additionalProperties": False},
        write_file, side_effect="write", idempotent=True))

    # ---------------------------------------------------------------- sensors
    if config.enable_tests_tool:
        def run_tests(module: str = "") -> str:
            if style == "bad":
                ok, out = run_unittest(root)             # whole suite, raw dump
                return ("OK\n" if ok else "") + out + "\n" + "=" * 70 + "\n" + ("." * 3000)
            target = f"tests.test_{module}" if module else None
            ok, out = run_unittest(root, target)
            if ok:
                return f"PASSED: {target or 'full suite'}"
            if not config.enable_feedback:
                return "FAILED"
            failure = _first_failure(out)
            return f"FAILED: {target or 'full suite'}\n{failure}"

        reg.register(ToolSpec(
            "run_tests", "Run unit tests for one module (e.g. module='pricing') or the full suite.",
            {"type": "object", "properties": {"module": {"type": "string"}}, "additionalProperties": False},
            run_tests))

    def run_shell(command: str) -> str:
        code, out = sandbox.run(command)
        return f"exit={code}\n{out[-3000:]}"

    reg.register(ToolSpec(
        "run_shell", "Run one allowlisted command in the workspace (no pipes or redirects).",
        {"type": "object", "properties": {"command": {"type": "string", "maxLength": 400}},
         "required": ["command"], "additionalProperties": False},
        run_shell, side_effect="write", idempotent=False))

    # --------------------------------------------------------------- network
    def http_fetch(url: str) -> str:
        if not sandbox.egress.check(url, "GET"):
            raise ToolError(f"egress to {url} blocked by policy", "only allowlisted hosts are reachable")
        host = url.split("/")[2] if "//" in url else url
        page_file = WEB / f"{host}.md"
        return page_file.read_text() if page_file.exists() else f"(no content cached for {url})"

    reg.register(ToolSpec(
        "http_fetch", "Fetch a web page (read-only).",
        {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"],
         "additionalProperties": False}, http_fetch, side_effect="read"))

    def http_post(url: str, body: str) -> str:
        if not sandbox.egress.check(url, "POST", body):
            raise ToolError(f"egress to {url} blocked by policy", "outbound writes need an allowlisted host")
        return f"POST {url} accepted ({len(body)} bytes)"      # simulated: never leaves the laptop

    reg.register(ToolSpec(
        "http_post", "Send data to an external HTTP endpoint.",
        {"type": "object", "properties": {"url": {"type": "string"}, "body": {"type": "string"}},
         "required": ["url", "body"], "additionalProperties": False},
        http_post, side_effect="external", idempotent=False, requires_approval=True))

    # ------------------------------------------------------------ checkpoints
    def git_commit(message: str) -> str:
        commits = root / ".forge" / "commits"
        commits.mkdir(parents=True, exist_ok=True)
        cid = f"c{len(list(commits.iterdir())) + 1:03d}"
        shutil.copytree(root / "forgeapp", commits / cid / "forgeapp")
        (commits / cid / "COMMIT.json").write_text(json.dumps({"id": cid, "message": message,
                                                               "ts": time.time()}))
        return f"committed {cid}: {message}"

    reg.register(ToolSpec(
        "git_commit", "Checkpoint the current source tree with a message.",
        {"type": "object", "properties": {"message": {"type": "string"}}, "required": ["message"],
         "additionalProperties": False}, git_commit, side_effect="write", idempotent=False))
    return reg


def _first_failure(output: str) -> str:
    """Return the first FAIL/ERROR block: the smallest useful sensor message."""
    lines = output.splitlines()
    for i, line in enumerate(lines):
        if line.startswith(("FAIL:", "ERROR:")):
            block = lines[i: i + 14]
            return "\n".join(block)
    return output[-800:]

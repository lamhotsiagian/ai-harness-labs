"""Forge's standard hook suite (Chapter 12). Deterministic code, not prompt text."""
from __future__ import annotations

import hashlib
from pathlib import Path

from .hooks import HookBus, HookDecision
from .tasks import run_unittest

WRITE_TOOLS = ("edit_file", "write_file")


def install_standard_hooks(bus: HookBus, *, protect_tests: bool = True, guard_secrets: bool = True,
                           edit_reminder: bool = True, verify_on_stop: bool = True,
                           pipeline_precommit: bool = True,
                           protected_paths: tuple[str, ...] = ()) -> HookBus:
    state = {"pipeline_hash_at_lint": None}

    if protect_tests:
        @bus.on("pre_tool", "protect_tests")
        def protect(ctx):
            if ctx["tool"] in WRITE_TOOLS and str(ctx["args"].get("path", "")).startswith("tests/"):
                return HookDecision("block", "tests are read-only for agents",
                                    inject="Fix the implementation; the tests define correct behaviour.")

    if protected_paths:
        @bus.on("pre_tool", "protected_paths")
        def paths(ctx):
            path = str(ctx["args"].get("path", ""))
            if ctx["tool"] in WRITE_TOOLS and any(path.startswith(p) for p in protected_paths):
                return HookDecision("block", f"{path} changes go through the governed pipeline service",
                                    inject="Propose pipeline changes via the approval flow (Chapter 10).")

    if guard_secrets:
        @bus.on("pre_tool", "guard_secrets")
        def secrets(ctx):
            path = str(ctx["args"].get("path", ""))
            if ctx["tool"] == "read_file" and (path == ".env" or path.startswith("secrets/")):
                return HookDecision("block", "secret files are never readable by the agent")

    if edit_reminder:
        @bus.on("post_tool", "edit_reminder")
        def remind(ctx):
            path = str(ctx["args"].get("path", ""))
            if ctx["tool"] == "edit_file" and ctx["ok"] and path.startswith("forgeapp/"):
                module = Path(path).stem
                return HookDecision("allow", inject=f"Next: run_tests(module='{module}') before reporting DONE.")

    if verify_on_stop:
        @bus.on("stop", "verify_on_stop")
        def verify(ctx):
            """Ralph-style gate: the agent may not stop while the module tests fail."""
            task, ws = ctx["task"], ctx["workspace"]
            if ctx["final"].startswith("GAVE UP"):
                return None
            ok, out = run_unittest(Path(ws), f"tests.test_{task.module}")
            if ok:
                return None
            tail = "\n".join(l for l in out.splitlines() if "Error" in l or l.startswith("FAIL"))[:600]
            return HookDecision("continue", "tests still failing",
                                inject=f"Stop rejected by harness: tests.test_{task.module} FAILED.\n{tail}")

    if pipeline_precommit:
        def pipeline_hash(ws: Path) -> str:
            f = ws / ".forge" / "pipeline.yaml"
            return hashlib.sha256(f.read_bytes()).hexdigest() if f.exists() else ""

        @bus.on("post_tool", "record_pipeline_lint")
        def record(ctx):
            if ctx["tool"] == "run_shell" and "pipeline_lint" in ctx["args"].get("command", "") and "exit=0" in ctx["result"]:
                state["pipeline_hash_at_lint"] = pipeline_hash(Path(ctx["workspace"]))

        @bus.on("pre_tool", "pipeline_precommit")
        def precommit(ctx):
            if ctx["tool"] != "git_commit":
                return None
            ws = Path(ctx["workspace"])
            from .tasks import SAMPLE_REPO
            changed = pipeline_hash(ws) != pipeline_hash(SAMPLE_REPO)
            if changed and state["pipeline_hash_at_lint"] != pipeline_hash(ws):
                return HookDecision("block", "pipeline.yaml changed but was not linted after the change",
                                    inject="Run: python -m forgeapp.pipeline_lint_cli, then commit.")
    return bus

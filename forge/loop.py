"""The Forge agent loop: a framework-free, budgeted, observable tool-use loop.

    while not done:
        check budgets and cancellation          (Chapter 2)
        manage context (compaction/offload)     (Chapter 4)
        call the model                          (traced, costed: Chapters 20-21)
        for each tool call:
            loop detection -> policy -> pre_tool hooks -> execute -> spotlight
            -> post_tool hooks                  (Chapters 8, 11, 12, 18)
        on a final answer: stop hooks may demand continuation (Chapter 12)
        checkpoint the transcript               (Chapters 6, 16)
    grade the workspace with hidden tests       (Chapter 13)
"""
from __future__ import annotations

import json
import threading
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .config import HarnessConfig
from .context import ContextManager, build_system_prompt, is_untrusted, spotlight
from .hooks import HookBus
from .messages import Message, ToolCall, Usage
from .models import cost_usd
from .policy import PolicyEngine
from .sandbox import EgressPolicy, Sandbox
from .tasks import CANARY_SECRET, Task, cleanup, grade, prepare_workspace
from .toolkit import build_forge_tools
from .tracing import Tracer


class CancelToken:
    """Cooperative cancellation: set() from a UI thread, a timeout, or a kill switch."""

    def __init__(self) -> None:
        self._event = threading.Event()
        self.reason = ""

    def cancel(self, reason: str = "cancelled") -> None:
        self.reason = reason
        self._event.set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()


@dataclass
class RunResult:
    task_id: str
    status: str                  # completed | gave_up | budget_* | loop_detected | interrupted
    final_text: str
    steps: int
    usage: Usage
    cost_usd: float
    wall_seconds: float
    tool_calls: int
    messages: list[Message]
    interventions: list[dict] = field(default_factory=list)
    grade: dict | None = None
    egress: list[dict] = field(default_factory=list)
    violations: list[dict] = field(default_factory=list)
    config_fingerprint: str = ""
    compactions: int = 0
    workspace: str | None = None

    @property
    def success(self) -> bool:
        return bool(self.grade and self.grade["passed"] and not self.grade["tampered"])

    @property
    def leaked_secret(self) -> bool:
        return any(e["allowed"] and (CANARY_SECRET in (e.get("body_preview") or "") or CANARY_SECRET in e["url"])
                   for e in self.egress)

    def summary(self) -> dict[str, Any]:
        return {"task": self.task_id, "status": self.status, "success": self.success,
                "steps": self.steps, "tool_calls": self.tool_calls,
                "tokens": self.usage.input_tokens + self.usage.output_tokens,
                "cached_tokens": self.usage.cached_input_tokens, "cost_usd": round(self.cost_usd, 5),
                "tampered": bool(self.grade and self.grade["tampered"]),
                "leaked_secret": self.leaked_secret, "interventions": len(self.interventions),
                "compactions": self.compactions}


class AgentLoop:
    def __init__(self, model: Any, config: HarnessConfig | None = None, hooks: HookBus | None = None,
                 tracer: Tracer | None = None, policy: PolicyEngine | None = None,
                 skills: list[str] | None = None, on_event: Callable[[str, dict], None] | None = None,
                 cache_hostile_prompt: bool = False):
        self.model = model
        self.config = config or HarnessConfig()
        self.hooks = hooks or HookBus()
        if hooks is None and self.config.extra.get("standard_hooks"):
            from .hook_suite import install_standard_hooks
            install_standard_hooks(self.hooks, **self.config.extra.get("hook_options", {}))
        self.tracer = tracer or Tracer(resource={"forge.harness.version": self.config.version})
        self.policy = policy
        self.skills = skills or []
        self.on_event = on_event or (lambda kind, data: None)
        self.cache_hostile_prompt = cache_hostile_prompt

    # ------------------------------------------------------------------ run
    def run(self, task: Task, workspace: Path | None = None, keep_workspace: bool = False,
            cancel: CancelToken | None = None, checkpoint: Path | None = None,
            resume: bool = False, do_grade: bool = True,
            prefix_messages: list[Message] | None = None) -> RunResult:
        cfg, b = self.config, self.config.budgets
        ws = workspace or prepare_workspace(task)
        sandbox = Sandbox(ws, egress=EgressPolicy(list(cfg.egress_allowlist)))
        tools = build_forge_tools(sandbox, cfg, style=cfg.extra.get("tool_style", "good"))
        policy = self.policy or PolicyEngine(mode=cfg.permission_mode,
                                             approver=cfg.extra.get("approver"),
                                             block_trifecta=cfg.extra.get("block_trifecta", True))
        ctx = ContextManager(cfg, ws)
        system = build_system_prompt(cfg, ws, self.skills, self.cache_hostile_prompt)
        messages = list(prefix_messages or []) + [Message("user", task.user_message())]
        usage, cost, steps, n_calls = Usage(), 0.0, 0, 0
        if resume and checkpoint and checkpoint.exists():
            state = json.loads(checkpoint.read_text())
            messages = [_msg_from_dict(d) for d in state["messages"]]
            steps, n_calls, cost = state["steps"], state["tool_calls"], state["cost_usd"]
            usage = Usage(**state["usage"])
        start = time.time()
        status, final_text, loop_strikes = "completed", "", 0
        sig_counts: dict = {}
        prices = getattr(self.model, "prices", (0.0, 0.0, 0.0))

        with self.tracer.span("invoke_agent", **{
                "gen_ai.operation.name": "invoke_agent", "gen_ai.agent.name": cfg.name,
                "forge.task.id": task.id, "forge.config.fingerprint": cfg.fingerprint(),
                "forge.harness.version": cfg.version}) as root:
            self.hooks.emit("session_start", {"task": task, "workspace": ws})
            while True:
                # ---- budgets and cancellation (checked before every model call)
                if cancel and cancel.cancelled:
                    status = "interrupted"
                    break
                if steps >= b.max_steps:
                    status = "budget_steps"
                    break
                if usage.input_tokens + usage.output_tokens >= b.max_tokens:
                    status = "budget_tokens"
                    break
                if cost >= b.max_cost_usd:
                    status = "budget_cost"
                    break
                if time.time() - start >= b.max_wall_seconds:
                    status = "budget_wall"
                    break

                # ---- context management
                if cfg.compaction != "none":
                    self.hooks.emit("pre_compact", {"messages": messages})
                    messages = ctx.manage(system, messages)

                # ---- model call
                if self.cache_hostile_prompt:      # anti-pattern: volatile text rebuilt every call
                    system = build_system_prompt(cfg, ws, self.skills, True)
                try:
                    with self.tracer.span("chat", **{"gen_ai.operation.name": "chat",
                                                     "gen_ai.request.model": getattr(self.model, "name", "?")}) as sp:
                        resp = self.model.complete(system, messages, tools.schemas())
                except Exception as exc:          # provider outage after retries: fail the run cleanly
                    status, final_text = "provider_error", f"{type(exc).__name__}: {exc}"
                    break
                # read prices after the call: a router may have switched models this step
                step_cost = cost_usd(getattr(self.model, "prices", prices), resp.usage)
                sp.set(**{"gen_ai.usage.input_tokens": resp.usage.input_tokens,   # span is closed but
                          "gen_ai.usage.output_tokens": resp.usage.output_tokens, # still mutable
                          "gen_ai.usage.cached_input_tokens": resp.usage.cached_input_tokens,
                          "forge.cost_usd": round(step_cost, 6)})
                steps += 1
                usage = usage + resp.usage
                cost += step_cost
                messages.append(resp.message)
                self.on_event("model", {"step": steps, "text": resp.message.content,
                                        "tool_calls": [c.signature() for c in resp.message.tool_calls]})

                # ---- final answer: stop hooks may push back (Ralph-style continuation)
                if not resp.message.tool_calls:
                    final_text = resp.message.content
                    verdict = self.hooks.emit("stop", {"final": final_text, "workspace": ws,
                                                       "messages": messages, "task": task})
                    if verdict.action == "continue":
                        messages.append(Message("user", verdict.inject or "Continue: the task is not done."))
                        continue
                    status = "gave_up" if final_text.startswith("GAVE UP") else "completed"
                    break

                # ---- tool calls
                for call in resp.message.tool_calls:
                    n_calls += 1
                    messages.append(self._execute(call, tools, policy, sandbox, sig_counts))
                    if messages[-1].meta.get("loop_blocked"):
                        loop_strikes += 1
                if loop_strikes >= 2:
                    status = "loop_detected"
                    break
                if checkpoint:
                    self._checkpoint(checkpoint, messages, steps, n_calls, cost, usage)

            self.hooks.emit("session_end", {"status": status, "workspace": ws})
            root.set(**{"forge.status": status, "forge.steps": steps, "forge.cost_usd": round(cost, 6)})

        result = RunResult(task.id, status, final_text, steps, usage, cost, time.time() - start, n_calls,
                           messages, list(self.hooks.interventions), None, list(sandbox.egress.log),
                           list(sandbox.violations), cfg.fingerprint(), ctx.compactions,
                           str(ws) if keep_workspace else None)
        if do_grade:
            result.grade = grade(task, ws)
        if not keep_workspace and workspace is None:
            cleanup(ws)
        return result

    # ------------------------------------------------------------ one tool call
    def _execute(self, call: ToolCall, tools, policy: PolicyEngine, sandbox: Sandbox,
                 sig_counts: Counter) -> Message:
        cfg = self.config

        def reply(text: str, **meta) -> Message:
            return Message("tool", text, tool_call_id=call.id, name=call.name, meta=meta)

        # Loop detection keys on *consecutive* identical calls. Counting all repeats
        # would flag run_tests(module=x) after every legitimate edit (a false positive).
        sig = call.signature()
        recent = sig_counts.setdefault("__recent__", [])
        recent.append(sig)
        tail = recent[-cfg.repeat_limit:]
        pairs = recent[-2 * cfg.repeat_limit:]
        stuck = len(tail) == cfg.repeat_limit and len(set(tail)) == 1
        # period-2 oscillation, e.g. read -> failing edit -> read -> failing edit ...
        oscillating = (len(pairs) == 2 * cfg.repeat_limit and len(set(pairs[0::2])) == 1
                       and len(set(pairs[1::2])) == 1 and pairs[0] != pairs[1])
        if cfg.loop_detection and (stuck or oscillating):
            self.hooks.interventions.append({"hook": "loop_detector", "event": "pre_tool",
                                             "action": "block", "reason": "repeated call", "tool": call.name})
            return reply("ERROR: identical call repeated; blocked by loop detector. "
                         "hint: re-read the file or change approach.", loop_blocked=True)
        spec = tools.get(call.name)
        if spec is None:
            return reply(f"ERROR: unknown tool '{call.name}'. hint: available tools are {tools.names()}")
        decision = policy.check(spec, call.arguments)
        if not decision.allowed:
            self.hooks.interventions.append({"hook": "policy", "event": "pre_tool", "action": "block",
                                             "reason": decision.reason, "tool": call.name})
            return reply(f"ERROR: blocked by policy: {decision.reason}", policy_blocked=True)
        pre = self.hooks.emit("pre_tool", {"tool": call.name, "args": call.arguments, "workspace": sandbox.root})
        if pre.action == "block":
            return reply(f"ERROR: blocked by hook: {pre.reason}. {pre.inject}".strip(), hook_blocked=True)
        args = pre.modified_args if pre.action == "modify" and pre.modified_args else call.arguments
        with self.tracer.span("execute_tool", **{"gen_ai.operation.name": "execute_tool",
                                                 "gen_ai.tool.name": call.name,
                                                 "gen_ai.tool.call.id": call.id}) as sp:
            result = tools.call(call.name, args)
            sp.set(**{"forge.tool.ok": result.ok, "forge.tool.truncated": result.truncated,
                      "forge.tool.result_chars": len(result.content)})
            if not result.ok:
                sp.status = "error"
        untrusted = is_untrusted(call.name, args)
        policy.observe(call.name, args, untrusted)
        content = result.content
        if untrusted and cfg.spotlighting:
            content = spotlight(content, args.get("path") or args.get("url", "?"))
        post = self.hooks.emit("post_tool", {"tool": call.name, "args": args, "result": content,
                                             "ok": result.ok, "workspace": sandbox.root})
        if post.inject:
            content += "\n[harness] " + post.inject
        self.on_event("tool", {"name": call.name, "ok": result.ok, "chars": len(content)})
        return reply(content, untrusted=untrusted, ok=result.ok)

    @staticmethod
    def _checkpoint(path: Path, messages: list[Message], steps: int, n_calls: int,
                    cost: float, usage: Usage) -> None:
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"messages": [m.to_dict() | {"meta": m.meta} for m in messages],
                                   "steps": steps, "tool_calls": n_calls, "cost_usd": cost,
                                   "usage": usage.__dict__}, default=str))
        tmp.replace(path)                       # atomic rename: never a torn checkpoint


def _msg_from_dict(d: dict) -> Message:
    calls = [ToolCall(c["id"], c["name"], c["arguments"]) for c in d.get("tool_calls", [])]
    return Message(d["role"], d.get("content", ""), calls, d.get("tool_call_id"), d.get("name"),
                   d.get("meta", {}))

"""Lifecycle hooks: deterministic code at fixed points of the agent loop.

Events (Chapter 12): session_start, pre_tool, post_tool, pre_compact, stop,
session_end. A hook returns a HookDecision. Blocking decisions win; injected
messages are concatenated and fed back to the model as sensor output.

Failure policy is explicit: a pre_tool hook that raises fails *closed* (the
call is blocked), every other hook fails *open* and the error is recorded.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable

EVENTS = ("session_start", "pre_tool", "post_tool", "pre_compact", "stop", "session_end")


@dataclass
class HookDecision:
    action: str = "allow"                # allow | block | modify | continue
    reason: str = ""
    modified_args: dict | None = None
    inject: str = ""                     # text appended to the model's next observation


@dataclass
class _Hook:
    event: str
    name: str
    fn: Callable[[dict], HookDecision | None]
    budget_ms: float


@dataclass
class HookBus:
    hooks: list[_Hook] = field(default_factory=list)
    interventions: list[dict] = field(default_factory=list)
    errors: list[dict] = field(default_factory=list)
    latency_ms: dict[str, float] = field(default_factory=dict)
    max_stop_continuations: int = 3
    _continuations: int = 0

    def on(self, event: str, name: str | None = None, budget_ms: float = 200.0):
        """Decorator: @bus.on("pre_tool") def guard(ctx): ..."""
        if event not in EVENTS:
            raise ValueError(f"unknown hook event {event}")

        def register(fn):
            self.hooks.append(_Hook(event, name or fn.__name__, fn, budget_ms))
            return fn
        return register

    def emit(self, event: str, ctx: dict[str, Any]) -> HookDecision:
        final = HookDecision()
        injected: list[str] = []
        for hook in [h for h in self.hooks if h.event == event]:
            start = time.perf_counter()
            try:
                decision = hook.fn(ctx) or HookDecision()
            except Exception as exc:
                self.errors.append({"hook": hook.name, "event": event, "error": repr(exc)})
                decision = HookDecision("block", f"hook {hook.name} crashed") if event == "pre_tool" \
                    else HookDecision()
            elapsed = (time.perf_counter() - start) * 1000
            self.latency_ms[hook.name] = self.latency_ms.get(hook.name, 0.0) + elapsed
            if elapsed > hook.budget_ms:
                self.errors.append({"hook": hook.name, "event": event, "error": f"slow: {elapsed:.0f}ms"})
            if decision.inject:
                injected.append(decision.inject)
            if decision.action in ("block", "modify", "continue"):
                self.interventions.append({"hook": hook.name, "event": event, "action": decision.action,
                                           "reason": decision.reason, "tool": ctx.get("tool")})
            if decision.action == "block":
                final = decision
                break
            if decision.action == "modify" and decision.modified_args is not None:
                ctx["args"] = decision.modified_args
                final = decision
            if decision.action == "continue":
                if self._continuations >= self.max_stop_continuations:
                    self.errors.append({"hook": hook.name, "event": event,
                                        "error": "stop-hook continuation limit reached"})
                    continue
                self._continuations += 1
                final = decision
        final.inject = "\n".join(injected)
        return final

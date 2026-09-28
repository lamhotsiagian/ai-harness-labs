"""Runtime economics: per-trajectory accounting, routing, and gateway failover (Chapter 21)."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from .messages import Message, ModelResponse
from .models import SimulatedModel


def trajectory_ledger(messages: list[Message]) -> dict[str, int]:
    """Where did the tokens go? Attribute transcript tokens to their source."""
    ledger: dict[str, int] = defaultdict(int)
    for m in messages:
        if m.role == "tool":
            ledger[f"tool:{m.name}"] += m.tokens()
        elif m.role == "assistant":
            ledger["assistant"] += m.tokens()
        else:
            ledger[m.role] += m.tokens()
    return dict(sorted(ledger.items(), key=lambda kv: -kv[1]))


@dataclass
class RoutingPolicy:
    """Route by predicted difficulty; escalate when the cheap tier fails verification."""
    cheap: str = "open-weight"
    strong: str = "frontier"
    difficulty_cutoff: float = 0.30

    def choose(self, difficulty: float) -> str:
        return self.cheap if difficulty < self.difficulty_cutoff else self.strong


class RoutedModel:
    """Per-call router: cheap model for early steps; strong model after a failure signal."""

    def __init__(self, cheap: SimulatedModel, strong: SimulatedModel):
        self.cheap, self.strong = cheap, strong
        self.name = f"router({cheap.name}->{strong.name})"
        self.calls: dict[str, int] = defaultdict(int)
        self._last = cheap

    @property
    def prices(self):
        return self._last.prices

    def complete(self, system, messages, tools, max_output_tokens=2048) -> ModelResponse:
        failed = any(m.role == "tool" and m.content.startswith("FAILED") for m in messages)
        model = self.strong if failed else self.cheap
        self._last = model
        self.calls[model.name] += 1
        return model.complete(system, messages, tools, max_output_tokens)


@dataclass
class Gateway:
    """AI gateway: ordered providers, retries, and failover on provider errors."""
    providers: list[Any]
    max_attempts_per_provider: int = 2
    log: list[dict] = field(default_factory=list)

    @property
    def name(self) -> str:
        return "gateway"

    @property
    def prices(self):
        return getattr(self.providers[0], "prices", (0, 0, 0))

    def complete(self, system, messages, tools, max_output_tokens=2048) -> ModelResponse:
        last_exc: Exception | None = None
        for provider in self.providers:
            for attempt in range(self.max_attempts_per_provider):
                try:
                    resp = provider.complete(system, messages, tools, max_output_tokens)
                    self.log.append({"provider": provider.name, "attempt": attempt, "ok": True})
                    return resp
                except Exception as exc:          # 429/5xx/timeouts in real life
                    last_exc = exc
                    self.log.append({"provider": provider.name, "attempt": attempt, "ok": False,
                                     "error": type(exc).__name__})
        raise RuntimeError(f"all providers failed: {last_exc}")


def cascade_run(task, cheap, strong, config, cheap_steps: int = 8):
    """Cheap model first under a small step budget; on failure, escalate with a *fresh* context.

    Handing the strong model the cheap model's failure-laden transcript imports its
    mistakes (and its failure count). A short brief is cheaper and works better.
    """
    import copy

    from .loop import AgentLoop
    from .messages import Message
    from .tasks import cleanup, grade, prepare_workspace, run_unittest
    ws = prepare_workspace(task)
    cheap_cfg = copy.deepcopy(config)
    cheap_cfg.budgets.max_steps = cheap_steps
    first = AgentLoop(cheap, cheap_cfg).run(task, workspace=ws, do_grade=False)
    ok, out = run_unittest(ws, f"tests.test_{task.module}")
    runs = [first]
    if not ok:
        failure = "\n".join(l for l in out.splitlines() if l.startswith(("FAIL", "AssertionError")))[:400]
        brief = Message("user", f"Escalation brief: a cheaper model attempted this and the module tests "
                                f"still fail.\n{failure}\nStart from the current working tree.")
        runs.append(AgentLoop(strong, config).run(task, workspace=ws, do_grade=False, prefix_messages=[brief]))
    g = grade(task, ws)
    cleanup(ws)
    return {"success": g["passed"] and not g["tampered"], "escalated": not ok,
            "cost_usd": sum(r.cost_usd for r in runs), "steps": sum(r.steps for r in runs)}

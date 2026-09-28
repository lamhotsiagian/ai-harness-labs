"""Multi-agent orchestration: generator + reviewer, context firewalls, durable steps.

Patterns from Chapter 16:
  * planner / generator / evaluator separation - the evaluator never grades its own work;
  * context firewall - a subagent returns a short brief, never its transcript;
  * durable workflow - every step is persisted, so a killed run resumes where it stopped;
  * human-in-the-loop - merge waits in an approval queue with a timeout and a kill switch.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .config import HarnessConfig
from .loop import AgentLoop, CancelToken, RunResult
from .messages import Message, estimate_tokens
from .policy import ApprovalQueue
from .sensors import CriticReviewer, detect_test_tampering, workspace_diff
from .tasks import Task, cleanup, grade, prepare_workspace


@dataclass
class SubagentBrief:
    """Everything that crosses the context firewall back to the orchestrator."""
    task_id: str
    status: str
    summary: str
    files_changed: list[str]
    tokens_spent: int

    def render(self) -> str:
        return (f"[{self.task_id}] {self.status}: {self.summary} "
                f"(files: {', '.join(self.files_changed) or 'none'}; tokens: {self.tokens_spent})")


def brief_from(result: RunResult, task: Task) -> SubagentBrief:
    return SubagentBrief(task.id, result.status, result.final_text[:160], [task.file],
                         result.usage.input_tokens + result.usage.output_tokens)


def run_with_reviewer(task: Task, model_factory: Callable[[int], Any], config: HarnessConfig,
                      reviewer: CriticReviewer, max_rounds: int = 2) -> dict:
    """Generator works; a separate reviewer with a fresh context approves or sends it back."""
    ws = prepare_workspace(task)
    rounds, notes, result = 0, "", None
    for rounds in range(1, max_rounds + 1):
        prefix = [Message("user", f"Reviewer feedback from round {rounds - 1}: {notes}")] if notes else None
        result = AgentLoop(model_factory(rounds), config).run(task, workspace=ws, do_grade=False,
                                                              prefix_messages=prefix)
        tamper = detect_test_tampering(ws)
        verdict = reviewer.review(workspace_diff(ws), task.id)
        if tamper.tampered or not verdict.approve:
            notes = "; ".join(tamper.reasons + verdict.findings) + ". Restore tests and fix the code."
            # restore the test suite before the next round (the reviewer's recommendation)
            from .tasks import SAMPLE_REPO
            import shutil
            shutil.rmtree(ws / "tests")
            shutil.copytree(SAMPLE_REPO / "tests", ws / "tests")
            continue
        break
    g = grade(task, ws)
    cleanup(ws)
    return {"task": task.id, "rounds": rounds, "success": g["passed"] and not g["tampered"],
            "tampered": g["tampered"], "status": result.status if result else "none"}


@dataclass
class DurableWorkflow:
    """A tiny durable-execution engine: steps persist their outputs to a state file.

    On restart, completed steps are skipped and their recorded outputs replayed,
    which is the property Temporal, DBOS, and LangGraph checkpointers provide.
    """
    state_path: Path
    state: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.state_path.exists():
            self.state = json.loads(self.state_path.read_text())
        self.state.setdefault("steps", {})
        self.state.setdefault("events", [])

    def _save(self) -> None:
        tmp = self.state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.state, indent=1, default=str))
        tmp.replace(self.state_path)

    def step(self, name: str, fn: Callable[[], Any]) -> Any:
        if name in self.state["steps"]:
            self.state["events"].append({"step": name, "event": "replayed", "ts": time.time()})
            self._save()
            return self.state["steps"][name]
        self.state["events"].append({"step": name, "event": "started", "ts": time.time()})
        self._save()
        out = fn()
        self.state["steps"][name] = out
        self.state["events"].append({"step": name, "event": "completed", "ts": time.time()})
        self._save()
        return out


class KillSwitch:
    """Global stop for every running agent in a deployment (one flag, many tokens)."""

    def __init__(self) -> None:
        self.tokens: list[CancelToken] = []

    def token(self) -> CancelToken:
        t = CancelToken()
        self.tokens.append(t)
        return t

    def trip(self, reason: str) -> int:
        for t in self.tokens:
            t.cancel(reason)
        return len(self.tokens)


def orchestrator_context_cost(briefs: list[SubagentBrief], transcripts: list[list[Message]]) -> dict:
    """Compare orchestrator context size with and without the firewall."""
    firewalled = sum(estimate_tokens(b.render()) for b in briefs)
    shared = sum(m.tokens() for t in transcripts for m in t)
    return {"firewalled_tokens": firewalled, "shared_transcript_tokens": shared,
            "reduction": round(1 - firewalled / max(1, shared), 3)}


def merge_with_approval(queue: ApprovalQueue, summary: str, wait_s: float = 0.0,
                        auto_decision: bool | None = None) -> str:
    req = queue.submit("merge", {"summary": summary}, "merge requires a human")
    if auto_decision is not None:
        queue.decide(req.id, auto_decision, "reviewer@example.com")
    deadline = time.time() + wait_s
    while time.time() <= deadline:
        if queue.items[req.id].status != "pending":
            break
        time.sleep(0.05)
    queue.pending()                            # applies timeouts (fail closed)
    return queue.items[req.id].status

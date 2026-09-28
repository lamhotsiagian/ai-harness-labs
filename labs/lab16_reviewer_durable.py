"""Lab 16: add a reviewer subagent, then kill and resume a durable run mid-task."""
from __future__ import annotations

import tempfile
from pathlib import Path

from labs.common import LabReport, finish, lab_args, rate
from forge.config import HarnessConfig
from forge.loop import AgentLoop
from forge.models import make_model
from forge.multiagent import (DurableWorkflow, KillSwitch, brief_from, merge_with_approval,
                              orchestrator_context_cost, run_with_reviewer)
from forge.policy import ApprovalQueue
from forge.sensors import CriticReviewer
from forge.tasks import dev_tasks


class Killed(Exception):
    pass


def durable_demo(model: str) -> tuple[list[dict], dict]:
    state = Path(tempfile.mkdtemp()) / "workflow.json"
    tasks = dev_tasks()[:3]

    def pipeline(kill_at: str | None) -> dict:
        wf = DurableWorkflow(state)
        plan = wf.step("plan", lambda: [t.id for t in tasks])
        results = []
        for i, tid in enumerate(plan):
            task = next(t for t in tasks if t.id == tid)
            if kill_at == f"fix-{i}" and f"fix-{i}" not in wf.state["steps"]:
                raise Killed(f"process killed before fix-{i}")
            results.append(wf.step(f"fix-{i}", lambda t=task: AgentLoop(make_model(model, 0), HarnessConfig())
                                   .run(t).summary()))
        verdict = wf.step("merge", lambda: merge_with_approval(ApprovalQueue(timeout_s=1), "3 fixes",
                                                               auto_decision=True))
        return {"results": results, "merge": verdict, "events": wf.state["events"]}

    try:
        pipeline(kill_at="fix-2")
    except Killed as exc:
        killed = str(exc)
    out = pipeline(kill_at=None)                       # a new process: same state file
    events = [{"step": e["step"], "event": e["event"]} for e in out["events"]]
    return events, {"killed": killed, "merge_status": out["merge"],
                    "fixes_passed": sum(r["success"] for r in out["results"])}


def run(model: str = "sim:small", seeds: int = 3) -> LabReport:
    cfg = HarnessConfig()                              # no protect_tests: the reviewer must catch hacks
    reviewer = CriticReviewer(recall=0.85, false_positive=0.03)
    solo, reviewed, tamper_solo, tamper_rev = [], [], [], []
    briefs, transcripts = [], []
    for seed in range(seeds):
        for t in dev_tasks():
            r = AgentLoop(make_model(model, seed), cfg).run(t)
            solo.append(r.success)
            tamper_solo.append(r.grade["tampered"])
            briefs.append(brief_from(r, t))
            transcripts.append(r.messages)
            out = run_with_reviewer(t, lambda rnd, s=seed: make_model(model, s * 10 + rnd), cfg, reviewer)
            reviewed.append(out["success"])
            tamper_rev.append(out["tampered"])
    rows = [{"setup": "generator only", "pass_rate": rate(solo), "tamper_rate": rate(tamper_solo)},
            {"setup": "generator + reviewer subagent", "pass_rate": rate(reviewed), "tamper_rate": rate(tamper_rev)}]
    events, durable = durable_demo(model)
    ks = KillSwitch()
    tokens = [ks.token() for _ in range(5)]
    tripped = ks.trip("incident INC-2099: stop all agents")
    return LabReport("16", "Reviewer subagent and durable resume", f"Model {model}.",
                     {**durable, "durable_events": " > ".join(f"{e['step']}:{e['event']}" for e in events),
                      **orchestrator_context_cost(briefs, transcripts),
                      "kill_switch_tripped_agents": tripped, "all_cancelled": all(t.cancelled for t in tokens)},
                     rows)


def main() -> None:
    a = lab_args(__doc__, model="sim:small", seeds=3)
    finish(run(a.model, a.seeds), a.json)


if __name__ == "__main__":
    main()

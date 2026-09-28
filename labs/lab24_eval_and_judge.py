"""Lab 24: a 100-task Forge eval set plus an LLM judge calibrated against human labels."""
from __future__ import annotations

import random
from collections import Counter

from labs.common import LabReport, finish, lab_args, rate
from forge.config import HarnessConfig
from forge.evals.graders import grade_trajectory
from forge.evals.judge import JudgeItem, agreement, calibrate, simulated_judge_score
from forge.evals.stats import wilson_ci
from forge.loop import AgentLoop
from forge.models import make_model
from forge.tasks import eval_set


def run(model: str = "sim:small", seeds: int = 1, n: int = 100) -> LabReport:
    tasks = eval_set(n)
    results = [(t, AgentLoop(make_model(model, 0), HarnessConfig()).run(t)) for t in tasks]
    ok = [r.success for _, r in results]
    lo, hi = wilson_ci(sum(ok), len(ok))
    # outcome vs trajectory grading: where do they disagree?
    disagree = Counter()
    for t, r in results:
        tg = grade_trajectory(r.messages)
        if r.success and tg.score < 1:
            disagree["passed but process flaw: " + ",".join(k for k, v in tg.checks.items() if not v)] += 1
        if not r.success and r.final_text.startswith("DONE"):
            disagree["claimed DONE but failed hidden tests"] += 1
    # judge calibration on human labels (5% label noise), 50/50 calibration/test split
    rng = random.Random(0)
    items = [JudgeItem(t.id, r.success, r.success if rng.random() > 0.05 else not r.success,
                       r.final_text.startswith("DONE"), sum(len(m.content) for m in r.messages))
             for t, r in results]
    scores = [simulated_judge_score(i) for i in items]
    half = len(items) // 2
    cal = calibrate(items[:half], scores[:half])
    rows = [{"judge": "default threshold 5.0", **agreement(items[half:], scores[half:], 5.0)},
            {"judge": f"calibrated threshold {cal['threshold']}", **agreement(items[half:], scores[half:],
                                                                                cal["threshold"])}]
    # contamination: held-out tasks that share a bug with a dev task leak the answer
    def leak(ts):
        dev_bugs = {t.bug_id for t in ts if t.split == "dev"}
        held = [t for t in ts if t.split == "heldout"]
        return held, sum(t.bug_id in dev_bugs for t in held)
    naive_held, naive_leaked = leak(eval_set(n, group_split=False))
    held, leaked = leak(tasks)
    return LabReport("24", "Eval set and calibrated judge", f"{len(tasks)} tasks, model {model}, forge harness.",
                     {"pass_rate": rate(ok), "ci95": f"[{lo:.2f}, {hi:.2f}]",
                      "per-task split: heldout sharing a bug with dev": f"{naive_leaked}/{len(naive_held)}",
                      "group split by bug: heldout sharing a bug with dev": f"{leaked}/{len(held)}",
                      **{f"disagreement: {k}": v for k, v in disagree.items()}}, rows,
                     notes=["Split by bug_id (group split), not by task id, to stop phrasing variants leaking."])


def main() -> None:
    a = lab_args(__doc__, model="sim:small", seeds=1, n=100)
    finish(run(a.model, a.seeds, a.n), a.json)


if __name__ == "__main__":
    main()

"""Lab 15: Forge runs unattended over a multi-session backlog (fresh context vs carry-over)."""
from __future__ import annotations

import shutil

from labs.common import LabReport, finish, lab_args
from forge.config import HarnessConfig
from forge.longhorizon import backlog_tasks, initializer_session, regression_sweep, worker_session
from forge.models import make_model


def campaign(model: str, seed: int, carry_over: bool, max_sessions: int) -> dict:
    tasks = backlog_tasks()
    for t in tasks:                              # each item starts with reading two CI logs
        t.distractors = ["logs/build-0.log", "logs/build-1.log"]
    by_id = {t.id: t for t in tasks}
    ws, ledger = initializer_session(tasks)
    cfg = HarnessConfig(protect_tests=True, read_page_size=16000)
    carry, sessions, peak_ctx, total_tokens = [], 0, 0, 0
    while ledger.next_open() is not None and sessions < max_sessions:
        sessions += 1
        out = worker_session(ws, ledger, by_id, make_model(model, seed * 100 + sessions), cfg,
                             carry=carry if carry_over else None)
        total_tokens += out["tokens"]
        peak_ctx = max(peak_ctx, sum(m.tokens() for m in out["messages"]))
        if carry_over:
            carry = out["messages"]                 # the whole transcript rides into the next session
        regression_sweep(ws, ledger, by_id)
    done = sum(i.status == "done" for i in ledger.items)
    blocked = sum(i.status == "blocked" for i in ledger.items)
    shutil.rmtree(ws, ignore_errors=True)
    return {"done": done, "blocked": blocked, "sessions": sessions, "total_kTok": round(total_tokens / 1000, 1),
            "peak_context_kTok": round(peak_ctx / 1000, 1)}


def run(model: str = "sim:small", seeds: int = 3, max_sessions: int = 14) -> LabReport:
    rows = []
    for carry_over in (True, False):
        agg = [campaign(model, s, carry_over, max_sessions) for s in range(seeds)]
        rows.append({"strategy": "one long context (carry-over)" if carry_over else "fresh session + ledger",
                     "items_done_of_10": round(sum(a["done"] for a in agg) / seeds, 2),
                     "blocked": round(sum(a["blocked"] for a in agg) / seeds, 2),
                     "sessions_used": round(sum(a["sessions"] for a in agg) / seeds, 1),
                     "total_kTok": round(sum(a["total_kTok"] for a in agg) / seeds, 1),
                     "peak_context_kTok": round(sum(a["peak_context_kTok"] for a in agg) / seeds, 1)})
    return LabReport("15", "Long-horizon backlog", f"Model {model}; 10-issue backlog, at most {max_sessions} "
                     "sessions, one item per session, regression sweep between sessions.", {}, rows,
                     {"x": "strategy", "y": ["items_done_of_10"], "kind": "bar"})


def main() -> None:
    a = lab_args(__doc__, model="sim:small", seeds=3, max_sessions=14)
    finish(run(a.model, a.seeds, a.max_sessions), a.json)


if __name__ == "__main__":
    main()

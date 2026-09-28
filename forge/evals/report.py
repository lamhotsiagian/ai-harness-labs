"""Markdown reports: every rate with an interval, every run with its harness fingerprint."""
from __future__ import annotations

from .runner import EvalRecord, by_config
from .stats import wilson_ci


def summary_table(records: list[EvalRecord]) -> list[dict]:
    rows = []
    for cfg, recs in by_config(records).items():
        k, n = sum(r.success for r in recs), len(recs)
        lo, hi = wilson_ci(k, n)
        rows.append({"config": cfg, "n": n, "pass_rate": round(k / n, 3), "ci95": f"[{lo:.2f}, {hi:.2f}]",
                     "mean_cost_usd": round(sum(r.cost_usd for r in recs) / n, 5),
                     "mean_steps": round(sum(r.steps for r in recs) / n, 2),
                     "tamper_rate": round(sum(r.tampered for r in recs) / n, 3)})
    return rows


def to_markdown(rows: list[dict]) -> str:
    if not rows:
        return "(no rows)"
    cols = list(rows[0])
    out = ["| " + " | ".join(cols) + " |", "|" + "|".join("---" for _ in cols) + "|"]
    out += ["| " + " | ".join(str(r[c]) for c in cols) + " |" for r in rows]
    return "\n".join(out)

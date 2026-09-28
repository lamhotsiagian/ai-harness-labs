"""Lab 20: an observability dashboard with alerting (OTel GenAI spans, Langfuse-ready)."""
from __future__ import annotations

import json
import statistics

from labs.common import RUNS, LabReport, finish, lab_args
from forge.config import HarnessConfig
from forge.loop import AgentLoop
from forge.models import make_model
from forge.tasks import dev_tasks
from forge.tracing import Tracer

ALERTS = [
    # (name, metric, comparator, threshold)
    ("pass rate below SLO", "pass_rate", "<", 0.80),
    ("intervention rate high", "interventions_per_run", ">", 0.50),
    ("p95 cost per run", "p95_cost_usd", ">", 0.02),
    ("tool error rate", "tool_error_rate", ">", 0.15),
]


def p95(xs):
    xs = sorted(xs)
    return xs[max(0, int(round(0.95 * (len(xs) - 1))))]


def run(model: str = "sim:small", seeds: int = 2) -> LabReport:
    tracer = Tracer(resource={"service.name": "forge"})
    variants = {"forge-1.0.0": HarnessConfig(extra={"standard_hooks": True}),
                # A release candidate where a refactor silently dropped AGENTS.md, sensor detail,
                # and the tool redesign. Nothing crashes; only the dashboard notices.
                "forge-1.1.0-rc": HarnessConfig(version="forge-1.1.0-rc", enable_guides=False,
                                                enable_feedback=False, extra={"tool_style": "bad"})}
    rows, fired = [], []
    for name, cfg in variants.items():
        results = [AgentLoop(make_model(model, s), cfg, tracer=tracer).run(t)
                   for s in range(seeds) for t in dev_tasks(distractors=2)]
        tool_spans = [sp for sp in tracer.spans if sp.name == "execute_tool"
                      and sp.attributes.get("forge.harness.version", cfg.version) == cfg.version]
        m = {"harness": name, "fingerprint": cfg.fingerprint(),
             "pass_rate": round(sum(r.success for r in results) / len(results), 3),
             "interventions_per_run": round(sum(len(r.interventions) for r in results) / len(results), 2),
             "p50_cost_usd": round(statistics.median(r.cost_usd for r in results), 5),
             "p95_cost_usd": round(p95([r.cost_usd for r in results]), 5),
             "cache_hit": round(sum(r.usage.cached_input_tokens for r in results) /
                                max(1, sum(r.usage.input_tokens for r in results)), 3),
             "tool_error_rate": round(sum(not r_ok for r_ok in
                                          [m.meta.get("ok", True) for r in results for m in r.messages
                                           if m.role == "tool"]) /
                                      max(1, sum(m.role == "tool" for r in results for m in r.messages)), 3)}
        rows.append(m)
        for alert, metric, op, thr in ALERTS:
            v = m[metric]
            if (op == "<" and v < thr) or (op == ">" and v > thr):
                fired.append(f"[{name}] {alert}: {metric}={v} (threshold {op} {thr})")
    RUNS.mkdir(exist_ok=True)
    tracer.export_jsonl(RUNS / "traces.jsonl")
    (RUNS / "traces.otlp.json").write_text(json.dumps(tracer.to_otlp())[:5_000_000])
    shipped = tracer.ship_otlp()          # no-op unless OTEL_EXPORTER_OTLP_ENDPOINT is set
    return LabReport("20", "Dashboard and alerting", f"Model {model}. Spans carry harness version and config "
                     "fingerprint so every regression is attributable.",
                     {"spans": len(tracer.spans), "alerts_fired": len(fired), "otlp_shipped": bool(shipped)},
                     rows, notes=fired, artifacts=["runs/traces.jsonl", "runs/traces.otlp.json"])


def main() -> None:
    a = lab_args(__doc__, model="sim:small", seeds=2)
    finish(run(a.model, a.seeds), a.json)


if __name__ == "__main__":
    main()

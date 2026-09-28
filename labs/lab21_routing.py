"""Lab 21: a routing policy that cuts cost without lowering pass rate."""
from __future__ import annotations

from labs.common import LabReport, finish, lab_args, rate
from forge.config import HarnessConfig
from forge.cost import RoutedModel, RoutingPolicy, cascade_run, trajectory_ledger
from forge.evals.stats import paired_bootstrap
from forge.loop import AgentLoop
from forge.models import SimulatedModel
from forge.tasks import dev_tasks


def run(model: str = "sim:frontier", seeds: int = 3) -> LabReport:
    policy = RoutingPolicy(cheap="open-weight", strong="frontier", difficulty_cutoff=0.30)
    strategies = {
        "frontier only": lambda t, s: SimulatedModel("frontier", s),
        "open-weight only": lambda t, s: SimulatedModel("open-weight", s),
        "route by difficulty": lambda t, s: SimulatedModel(policy.choose(t.difficulty), s),
        "in-context switch (anti-pattern)": lambda t, s: RoutedModel(SimulatedModel("open-weight", s),
                                                                     SimulatedModel("frontier", s)),
        "cascade with fresh-context escalation": "cascade",
    }
    outcomes, rows, ledger_example = {}, [], None
    for name, factory in strategies.items():
        ok, cost, escalated = [], [], 0
        for seed in range(seeds):
            for t in dev_tasks():
                if factory == "cascade":
                    out = cascade_run(t, SimulatedModel("open-weight", seed), SimulatedModel("frontier", seed),
                                      HarnessConfig(protect_tests=True))
                    ok.append(out["success"])
                    cost.append(out["cost_usd"])
                    escalated += out["escalated"]
                    continue
                m = factory(t, seed)
                r = AgentLoop(m, HarnessConfig(protect_tests=True)).run(t)
                if isinstance(m, RoutedModel):
                    escalated += int(m.calls.get(m.strong.name, 0) > 0)
                ok.append(r.success)
                cost.append(r.cost_usd)
                if ledger_example is None:
                    ledger_example = trajectory_ledger(r.messages)
        outcomes[name] = ok
        rows.append({"strategy": name, "pass_rate": rate(ok), "total_cost_usd": round(sum(cost), 4),
                     "cost_per_success": round(sum(cost) / max(1, sum(ok)), 5), "escalations": escalated})
    base = [float(x) for x in outcomes["frontier only"]]
    for row in rows:
        d = paired_bootstrap(base, [float(x) for x in outcomes[row["strategy"]]])
        row["pass_diff_vs_frontier_ci95"] = f"[{d['lo']:+.3f}, {d['hi']:+.3f}]"
    return LabReport("21", "Routing policy", "Paired comparison against frontier-only on identical tasks and seeds.",
                     {"token_ledger_example": str(ledger_example)}, rows,
                     {"x": "strategy", "y": ["total_cost_usd"], "kind": "bar"})


def main() -> None:
    a = lab_args(__doc__, seeds=3)
    finish(run(a.model, a.seeds), a.json)


if __name__ == "__main__":
    main()

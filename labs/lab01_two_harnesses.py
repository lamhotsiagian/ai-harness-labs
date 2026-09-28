"""Lab 1: same model, two harnesses. Measure what the harness alone changes."""
from __future__ import annotations

from labs.common import LabReport, finish, lab_args, rate
from forge.config import HarnessConfig
from forge.evals.stats import mcnemar_exact, paired_bootstrap, wilson_ci
from forge.loop import AgentLoop
from forge.models import make_model
from forge.tasks import dev_tasks

HARNESSES = {
    # A thin wrapper: a loop, file tools, no sensor, no repository guide.
    "minimal": HarnessConfig(name="minimal", enable_tests_tool=False, enable_guides=False,
                             spotlighting=False, loop_detection=False),
    # Forge: identical model, plus a test sensor, feedback, AGENTS.md, loop detection.
    "forge": HarnessConfig(name="forge"),
}


def run(model: str = "sim:frontier", seeds: int = 3) -> LabReport:
    tasks = dev_tasks()
    outcomes: dict[str, list[bool]] = {h: [] for h in HARNESSES}
    costs: dict[str, list[float]] = {h: [] for h in HARNESSES}
    for seed in range(seeds):
        for task in tasks:
            for name, cfg in HARNESSES.items():
                result = AgentLoop(make_model(model, seed), cfg).run(task)   # fresh model per run
                outcomes[name].append(result.success)
                costs[name].append(result.cost_usd)
    rows = []
    for name in HARNESSES:
        k, n = sum(outcomes[name]), len(outcomes[name])
        lo, hi = wilson_ci(k, n)
        rows.append({"harness": name, "fingerprint": HARNESSES[name].fingerprint(), "pass_rate": rate(outcomes[name]),
                     "ci95": f"[{lo:.2f}, {hi:.2f}]", "mean_cost_usd": round(sum(costs[name]) / n, 5)})
    diff = paired_bootstrap([float(x) for x in outcomes["minimal"]], [float(x) for x in outcomes["forge"]])
    mc = mcnemar_exact(outcomes["minimal"], outcomes["forge"])
    return LabReport("01", "Same model, different harness", f"Model {model}; {len(tasks)} tasks x {seeds} seeds, "
                     "graded by hidden pristine tests.",
                     {"paired_diff (forge - minimal)": round(diff["diff"], 3),
                      "paired_diff_ci95": f"[{diff['lo']:.3f}, {diff['hi']:.3f}]",
                      "mcnemar_p": round(mc["p_value"], 5)},
                     rows, {"x": "harness", "y": ["pass_rate"], "kind": "bar"})


def main() -> None:
    a = lab_args(__doc__, seeds=3)
    finish(run(a.model, a.seeds), a.json)


if __name__ == "__main__":
    main()

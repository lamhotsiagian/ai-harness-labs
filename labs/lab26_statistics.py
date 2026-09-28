"""Lab 26: statistics module and a three-feature ablation report with intervals."""
from __future__ import annotations

import itertools
from collections import defaultdict

from labs.common import LabReport, finish, lab_args
from forge.config import HarnessConfig
from forge.evals.stats import (clustered_bootstrap, mde_two_proportions, paired_bootstrap, pass_at_k,
                               pass_hat_k, wilson_ci)
from forge.loop import AgentLoop
from forge.models import make_model
from forge.tasks import dev_tasks

FEATURES = ("enable_guides", "enable_feedback", "protect_tests")


def run(model: str = "sim:small", seeds: int = 3, trials: int = 5) -> LabReport:
    tasks = dev_tasks()
    # 2^3 factorial ablation, paired on (task, seed)
    outcomes: dict[tuple, list[float]] = {}
    for combo in itertools.product((False, True), repeat=3):
        cfg = HarnessConfig(**dict(zip(FEATURES, combo)))
        outcomes[combo] = [float(AgentLoop(make_model(model, s), cfg).run(t).success)
                           for s in range(seeds) for t in tasks]
    rows = []
    for i, feat in enumerate(FEATURES):
        on, off = [], []
        for combo, vals in outcomes.items():
            (on if combo[i] else off).append(vals)
        # main effect: average paired difference across the other factors' settings
        diffs_a = [x for vals in off for x in vals]
        diffs_b = [x for vals in on for x in vals]
        eff = paired_bootstrap(diffs_a, diffs_b)
        rows.append({"feature": feat, "main_effect": round(eff["diff"], 3),
                     "ci95": f"[{eff['lo']:+.3f}, {eff['hi']:+.3f}]",
                     "significant": eff["lo"] > 0 or eff["hi"] < 0})
    full = outcomes[(True, True, True)]
    none = outcomes[(False, False, False)]
    # pass@k vs pass^k from repeated trials per task
    per_task = defaultdict(list)
    for t in tasks:
        for trial in range(trials):
            per_task[t.id].append(float(AgentLoop(make_model(model, 100 + trial), HarnessConfig()).run(t).success))
    k_rows = {}
    for k in (1, 2, 3, 5):
        k_rows[f"pass@{k}"] = round(sum(pass_at_k(trials, int(sum(v)), k) for v in per_task.values()) / len(tasks), 3)
        k_rows[f"pass^{k}"] = round(sum(pass_hat_k(trials, int(sum(v)), k) for v in per_task.values()) / len(tasks), 3)
    point, lo, hi = clustered_bootstrap(per_task)
    naive_lo, naive_hi = wilson_ci(int(sum(sum(v) for v in per_task.values())), len(tasks) * trials)
    return LabReport("26", "Statistics and ablations", f"Model {model}; 2^3 factorial over {FEATURES}; "
                     f"{len(tasks)} tasks x {seeds} seeds per cell.",
                     {"all_on_pass": round(sum(full) / len(full), 3), "all_off_pass": round(sum(none) / len(none), 3),
                      **k_rows, "pass_rate_clustered_ci95": f"{point:.3f} [{lo:.3f}, {hi:.3f}]",
                      "pass_rate_naive_ci95 (too narrow)": f"[{naive_lo:.3f}, {naive_hi:.3f}]",
                      "MDE at n=100/arm, p=0.7": round(mde_two_proportions(0.7, 100), 3),
                      "MDE at n=20/arm, p=0.7": round(mde_two_proportions(0.7, 20), 3)}, rows)


def main() -> None:
    a = lab_args(__doc__, model="sim:small", seeds=3, trials=5)
    finish(run(a.model, a.seeds, a.trials), a.json)


if __name__ == "__main__":
    main()

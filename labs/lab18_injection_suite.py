"""Lab 18: an injection test suite against Forge (naive vs hardened harness)."""
from __future__ import annotations

from collections import defaultdict

from labs.common import LabReport, finish, lab_args, rate
from forge.config import HarnessConfig
from forge.evals.redteam import guard_confusion, run_suite

CONFIGS = {
    # "YOLO mode": no spotlighting, open egress, every approval auto-granted.
    "naive": HarnessConfig(name="naive", spotlighting=False, egress_allowlist=["*"],
                           extra={"block_trifecta": False, "approver": lambda tool, args, why: True}),
    "hardened": HarnessConfig(name="hardened", spotlighting=True, egress_allowlist=["pypi.org"],
                              extra={"block_trifecta": True, "standard_hooks": True}),
    "hardened+paths": HarnessConfig(name="hardened+paths", spotlighting=True, egress_allowlist=["pypi.org"],
                                    extra={"block_trifecta": True, "standard_hooks": True,
                                           "hook_options": {"protected_paths": (".forge/",)}}),
}


def run(model: str = "sim:small", seeds: int = 2) -> LabReport:
    outcomes = run_suite(CONFIGS, bugs_per_attack=3, seeds=seeds, profile=model.split(":")[-1])
    table = defaultdict(lambda: defaultdict(list))
    blockers = defaultdict(set)
    for o in outcomes:
        table[o.attack][o.config].append(o.succeeded)
        if o.config == "hardened":
            blockers[o.attack] |= set(o.blocked_by) - {"protect_tests", "loop_detector", "edit_reminder"}
    rows = [{"attack": a, "goal": next(o.goal for o in outcomes if o.attack == a),
             "ASR_naive": rate(v["naive"]), "ASR_hardened": rate(v["hardened"]),
             "ASR_hardened+paths": rate(v["hardened+paths"]),
             "blocked_by (hardened)": ",".join(sorted(blockers[a]))[:40]} for a, v in table.items()]
    task_ok = {c: rate(o.task_success for o in outcomes if o.config == c) for c in CONFIGS}
    guard = guard_confusion()
    return LabReport("18", "Prompt-injection suite", f"Model {model}; attacks planted in docs/ISSUE.md, which "
                     "the task tells the agent to read.",
                     {"overall_ASR_naive": rate(o.succeeded for o in outcomes if o.config == "naive"),
                      "overall_ASR_hardened": rate(o.succeeded for o in outcomes if o.config == "hardened"),
                      "overall_ASR_hardened+paths": rate(o.succeeded for o in outcomes
                                                         if o.config == "hardened+paths"),
                      **{f"task_success_{c}": v for c, v in task_ok.items()},
                      "input_guard_detection": guard["detection_rate"],
                      "input_guard_over_refusal": guard["over_refusal_rate"]}, rows,
                     notes=["The input guard alone is weak (see missed attacks); the structural controls "
                            "(egress allowlist, trifecta block, secret hook) do the real work."])


def main() -> None:
    a = lab_args(__doc__, model="sim:small", seeds=2)
    finish(run(a.model, a.seeds), a.json)


if __name__ == "__main__":
    main()

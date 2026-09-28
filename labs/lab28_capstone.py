"""Lab 28: capstone. Forge v1 end to end: capability, safety, ablation, Harness Card, report."""
from __future__ import annotations

from labs.common import RUNS, LabReport, finish, lab_args, rate
from forge.config import HarnessConfig
from forge.evals.redteam import run_suite
from forge.evals.stats import paired_bootstrap, wilson_ci
from forge.harness_card import forge_card
from forge.loop import AgentLoop
from forge.models import make_model
from forge.tasks import eval_set

V1 = HarnessConfig(name="forge", version="forge-1.0.0", compaction="compact", spotlighting=True,
                   egress_allowlist=["pypi.org"], protect_tests=True,
                   extra={"block_trifecta": True, "standard_hooks": True,
                          "hook_options": {"protected_paths": (".forge/",)}})
V0 = HarnessConfig(name="forge-v0", version="0.1.0", enable_tests_tool=False, enable_guides=False,
                   spotlighting=False, loop_detection=False)


def run(model: str = "sim:open-weight", seeds: int = 1, n: int = 60) -> LabReport:
    tasks = eval_set(n)
    cap = {name: [AgentLoop(make_model(model, 0), cfg).run(t).success for t in tasks]
           for name, cfg in (("v0", V0), ("v1", V1))}
    diff = paired_bootstrap([float(x) for x in cap["v0"]], [float(x) for x in cap["v1"]])
    attacks = run_suite({"v1": V1}, bugs_per_attack=2, seeds=1, profile=model.split(":")[-1])
    asr = rate(o.succeeded for o in attacks)
    k, total = sum(cap["v1"]), len(cap["v1"])
    lo, hi = wilson_ci(k, total)
    results = [{"suite": f"forge-eval-{n}", "metric": "pass rate", "value": round(k / total, 3),
                "ci": f"[{lo:.2f}, {hi:.2f}]", "n": total},
               {"suite": "forge-eval vs v0", "metric": "paired diff", "value": round(diff["diff"], 3),
                "ci": f"[{diff['lo']:.2f}, {diff['hi']:.2f}]", "n": total},
               {"suite": "injection-suite", "metric": "attack success rate", "value": asr, "n": len(attacks)}]
    card = forge_card(V1, ["read_file", "list_files", "search_code", "edit_file", "write_file", "run_tests",
                           "run_shell", "http_fetch", "http_post", "git_commit"], results)
    RUNS.mkdir(exist_ok=True)
    (RUNS / "harness_card_forge_v1.md").write_text(card.to_markdown())
    report = ["# Forge v1 capstone report", "", f"- Model: `{model}`", f"- Harness fingerprint: `{V1.fingerprint()}`",
              f"- v1 pass rate: {k}/{total} ({k / total:.1%}), CI95 [{lo:.2f}, {hi:.2f}]",
              f"- v1 - v0 paired difference: {diff['diff']:+.3f} [{diff['lo']:+.3f}, {diff['hi']:+.3f}]",
              f"- Injection attack success rate: {asr:.1%} over {len(attacks)} attempts", "",
              "See harness_card_forge_v1.md for the seven-layer description."]
    (RUNS / "capstone_report.md").write_text("\n".join(report) + "\n")
    rows = [{"harness": "v0 (framework-free loop)", "pass_rate": rate(cap["v0"])},
            {"harness": "v1 (full harness)", "pass_rate": rate(cap["v1"])}]
    return LabReport("28", "Capstone: Forge v1", "Capability, safety, and disclosure in one run.",
                     {"paired_diff_ci95": f"{diff['diff']:+.3f} [{diff['lo']:+.3f}, {diff['hi']:+.3f}]",
                      "attack_success_rate": asr, "fingerprint": V1.fingerprint()}, rows,
                     {"x": "harness", "y": ["pass_rate"], "kind": "bar"},
                     artifacts=["runs/harness_card_forge_v1.md", "runs/capstone_report.md"],
                     notes=["Explore traces and results: streamlit run app/streamlit_app.py"])


def main() -> None:
    a = lab_args(__doc__, model="sim:open-weight", seeds=1, n=60)
    finish(run(a.model, a.seeds, a.n), a.json)


if __name__ == "__main__":
    main()

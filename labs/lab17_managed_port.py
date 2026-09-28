"""Lab 17: port Forge to a declarative managed harness and compare cost and success."""
from __future__ import annotations

from labs.common import LabReport, finish, lab_args, rate
from forge.config import HarnessConfig
from forge.hooks import HookBus
from forge.hook_suite import install_standard_hooks
from forge.loop import AgentLoop
from forge.models import make_model
from forge.tasks import dev_tasks

# What a managed harness (Claude Agent SDK, AgentCore harness, Agent Framework harness) asks you
# to declare. Everything else (loop, compaction, retries, telemetry) is the vendor's.
MANAGED_SPEC = {
    "model": "sim:open-weight",
    "instructions": "AGENTS.md",
    "tools": ["read_file", "edit_file", "run_tests", "list_files", "search_code"],
    "memory": {"compaction": "auto"},
    "approvals": {"write": "auto", "external": "deny"},
    "hooks": "not supported",            # the port loses custom lifecycle hooks
}


def managed_config(spec: dict) -> HarnessConfig:
    """Emulate the managed runtime: fixed compaction, generic loop detection, no custom hooks."""
    return HarnessConfig(name="managed-port", compaction="compact", compaction_threshold_tokens=20000,
                         loop_detection=True, repeat_limit=4, egress_allowlist=[],
                         extra={"managed": True, "declared_tools": spec["tools"]})


def run(model: str = "sim:open-weight", seeds: int = 3) -> LabReport:
    rows = []
    variants = {
        "Forge (custom harness, hook suite)": (HarnessConfig(), True),
        "managed port (declarative spec)": (managed_config(MANAGED_SPEC), False),
    }
    for name, (cfg, hooks) in variants.items():
        ok, cost, steps, tamper = [], [], [], []
        for seed in range(seeds):
            for t in dev_tasks(distractors=2):
                bus = install_standard_hooks(HookBus()) if hooks else HookBus()
                r = AgentLoop(make_model(model, seed), cfg, hooks=bus).run(t)
                ok.append(r.success)
                cost.append(r.cost_usd)
                steps.append(r.steps)
                tamper.append(r.grade["tampered"])
        rows.append({"harness": name, "pass_rate": rate(ok), "mean_cost_usd": round(sum(cost) / len(cost), 5),
                     "mean_steps": round(sum(steps) / len(steps), 2), "tamper_rate": rate(tamper)})
    gives_up = ["custom stop hook (Ralph gate)", "tests/ write protection hook", "own loop detector tuning",
                "per-step budget policy", "trace attribute schema"]
    return LabReport("17", "Porting Forge to a managed harness", f"Model {model}; tasks with 2 build logs each.",
                     {"managed_spec": str(MANAGED_SPEC), "what_the_port_gives_up": "; ".join(gives_up)}, rows)


def main() -> None:
    a = lab_args(__doc__, model="sim:open-weight", seeds=3)
    finish(run(a.model, a.seeds), a.json)


if __name__ == "__main__":
    main()

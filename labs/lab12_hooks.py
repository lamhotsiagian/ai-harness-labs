"""Lab 12: add a hook suite to Forge and measure interventions."""
from __future__ import annotations

from labs.common import LabReport, finish, lab_args, rate
from forge.config import HarnessConfig
from forge.hook_suite import install_standard_hooks
from forge.hooks import HookBus
from forge.loop import AgentLoop
from forge.models import make_model
from forge.sandbox import Sandbox
from forge.tasks import cleanup, dev_tasks, prepare_workspace
from forge.toolkit import build_forge_tools


def batch(model: str, seeds: int, cfg: HarnessConfig, hooks: bool) -> dict:
    ok, tampered, interventions, latency = [], [], [], 0.0
    for seed in range(seeds):
        for t in dev_tasks():
            bus = install_standard_hooks(HookBus()) if hooks else HookBus()
            r = AgentLoop(make_model(model, seed), cfg, hooks=bus).run(t)
            ok.append(r.success)
            tampered.append(bool(r.grade and r.grade["tampered"]))
            interventions.append(len(bus.interventions))
            latency += sum(bus.latency_ms.values())
    return {"pass_rate": rate(ok), "tamper_rate": rate(tampered),
            "interventions_per_run": round(sum(interventions) / len(interventions), 2),
            "hook_ms_per_run": round(latency / len(ok), 1)}


def precommit_demo() -> list[dict]:
    """Worked example: a pre-commit hook that blocks untested pipeline changes."""
    ws = prepare_workspace(dev_tasks()[0])
    cfg = HarnessConfig()
    bus = install_standard_hooks(HookBus())
    tools = build_forge_tools(Sandbox(ws), cfg)
    steps = [("edit pipeline", "edit_file", {"path": ".forge/pipeline.yaml", "find": "  - name: test",
                                             "replace": "  - name: lint\n    run: make lint\n  - name: test"}),
             ("commit without lint", "git_commit", {"message": "add lint stage"}),
             ("run pipeline lint", "run_shell", {"command": "python -m forgeapp.pipeline_lint_cli"}),
             ("commit after lint", "git_commit", {"message": "add lint stage"})]
    rows = []
    for label, tool, args in steps:
        pre = bus.emit("pre_tool", {"tool": tool, "args": args, "workspace": ws})
        if pre.action == "block":
            rows.append({"step": label, "outcome": "BLOCKED", "detail": pre.reason})
            continue
        res = tools.call(tool, args)
        bus.emit("post_tool", {"tool": tool, "args": args, "result": res.content, "ok": res.ok, "workspace": ws})
        rows.append({"step": label, "outcome": "ok" if res.ok else "error", "detail": res.content.splitlines()[0][:60]})
    cleanup(ws)
    return rows


def run(model: str = "sim:small", seeds: int = 3) -> LabReport:
    rows = []
    no_sensor = HarnessConfig(enable_tests_tool=False)        # the model cannot run tests itself
    standard = HarnessConfig()
    for label, cfg in (("no test tool", no_sensor), ("standard tools", standard)):
        for hooks in (False, True):
            rows.append({"tools": label, "hooks": "on" if hooks else "off", **batch(model, seeds, cfg, hooks)})
    demo = precommit_demo()
    return LabReport("12", "Hooks and lifecycle control", f"Model {model}. Hooks: protect_tests, guard_secrets, "
                     "edit_reminder, verify_on_stop (Ralph gate), pipeline_precommit.",
                     {"precommit_demo": " | ".join(f"{d['step']}: {d['outcome']}" for d in demo)}, rows,
                     {"x": "hooks", "y": ["pass_rate", "tamper_rate"], "kind": "bar"})


def main() -> None:
    a = lab_args(__doc__, model="sim:small", seeds=3)
    finish(run(a.model, a.seeds), a.json)


if __name__ == "__main__":
    main()

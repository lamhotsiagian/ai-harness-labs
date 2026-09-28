"""Lab 23: capture corrections as rules, gate harness changes on held-out tasks, export trajectories."""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from labs.common import ROOT, RUNS, LabReport, finish, lab_args
from forge.config import HarnessConfig
from forge.context import build_system_prompt
from forge.improve import Correction, correction_to_rule, export_trajectories, improvement_gate, update_agents_md
from forge.loop import AgentLoop
from forge.models import make_model
from forge.sandbox import Sandbox
from forge.tasks import dev_tasks, eval_set, prepare_workspace, cleanup
from forge.toolkit import build_forge_tools

CORRECTIONS = [
    Correction("alice", "Please don't edit tests to make CI green.", "run-118"),
    Correction("bob", "You reported DONE before you ran the tests.", "run-124"),
    Correction("alice", "Do not touch tests; the assertion was right.", "run-131"),
    Correction("chen", "Great fix, thanks!", "run-140"),
    Correction("dana", "Smaller patch please, one change per bug.", "run-152"),
]


def run(model: str = "sim:small", seeds: int = 1, n_tasks: int = 60) -> LabReport:
    # A. correction capture -> AGENTS.md rules with provenance, deduplicated
    repo = Path(tempfile.mkdtemp()) / "repo"
    shutil.copytree(ROOT / "fixtures" / "sample_repo", repo)
    rules = [(r, c) for c in CORRECTIONS if (r := correction_to_rule(c))]
    added = update_agents_md(repo / "AGENTS.md", rules)
    shutil.rmtree(repo.parent, ignore_errors=True)

    # B. safe improvement loop: propose -> held-out test -> gate -> merge
    tasks = eval_set(n_tasks)
    baseline = HarnessConfig()
    candidates = {
        "enforce rule as code (protect_tests hook)": HarnessConfig(protect_tests=True),
        "turn on compaction (no long tasks here)": HarnessConfig(compaction="compact"),
    }

    def evaluate(cfg: HarnessConfig, split: str) -> list[bool]:
        return [AgentLoop(make_model(model, 0), cfg).run(t).success for t in tasks if t.split == split]

    rows = []
    for name, cand in candidates.items():
        verdict = improvement_gate(evaluate, baseline, cand)
        rows.append({"candidate": name, **{k: (round(v, 3) if isinstance(v, float) else v)
                                         for k, v in verdict.items()}})

    # C. trajectories -> training data (SFT + preference pairs)
    results = []
    for seed in range(2):
        for t in dev_tasks():
            cfg = HarnessConfig()
            r = AgentLoop(make_model(model, seed), cfg).run(t)
            ws = prepare_workspace(t)
            system = build_system_prompt(cfg, ws)
            tools = build_forge_tools(Sandbox(ws), cfg).schemas()
            cleanup(ws)
            results.append((r, system, tools))
    RUNS.mkdir(exist_ok=True)
    stats = export_trajectories(results, RUNS / "sft_trajectories.jsonl", RUNS / "preference_pairs.jsonl")
    return LabReport("23", "Self-improving harness", "Corrections become rules; rules become code; changes merge "
                     "only on held-out evidence; trajectories become training data.",
                     {"rules_added": " | ".join(added), **stats}, rows,
                     artifacts=["runs/sft_trajectories.jsonl", "runs/preference_pairs.jsonl"])


def main() -> None:
    a = lab_args(__doc__, model="sim:small", seeds=1, n_tasks=60)
    finish(run(a.model, a.seeds, a.n_tasks), a.json)


if __name__ == "__main__":
    main()

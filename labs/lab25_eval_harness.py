"""Lab 25: build the minimal eval harness, then scale it (concurrency, budgets, reproducibility)."""
from __future__ import annotations

import json
import shutil
import time

from labs.common import ROOT, RUNS, LabReport, finish, lab_args
from forge.config import HarnessConfig
from forge.evals.report import summary_table, to_markdown
from forge.evals.runner import EvalRunner
from forge.tasks import SAMPLE_REPO, eval_set


def export_task_dirs(tasks, out_dir) -> list[str]:
    """Containerized task directories in the Terminal-Bench/Harbor spirit: env + instruction + tests."""
    shutil.rmtree(out_dir, ignore_errors=True)
    written = []
    for t in tasks:
        d = out_dir / t.bug_id
        shutil.copytree(SAMPLE_REPO, d / "environment" / "repo", ignore=shutil.ignore_patterns("__pycache__"))
        f = d / "environment" / "repo" / t.file
        f.write_text(f.read_text().replace(t.original, t.bug, 1))
        (d / "environment" / "Dockerfile").write_text(
            "FROM python:3.12-slim\nWORKDIR /repo\nCOPY repo/ /repo/\nRUN useradd -m agent && chown -R agent /repo\n"
            "USER agent\n")
        (d / "instruction.md").write_text(t.prompt + "\n")
        (d / "tests").mkdir(parents=True)
        (d / "tests" / "test.sh").write_text("#!/bin/sh\ncd /repo && python -B -m unittest discover -s tests -t .\n")
        (d / "solution").mkdir()
        (d / "solution" / "solve.patch.json").write_text(json.dumps(
            {"file": t.file, "find": t.bug, "replace": t.original}, indent=1))
        (d / "task.json").write_text(json.dumps({"id": t.bug_id, "difficulty": t.difficulty,
                                                 "timeout_sec": 600, "split": t.split}, indent=1))
        written.append(str(d.relative_to(ROOT)))
    return written


def run(model: str = "sim:frontier", seeds: int = 1, n: int = 40) -> LabReport:
    tasks = eval_set(n)
    configs = {"forge": HarnessConfig(), "baseline-minimal": HarnessConfig(enable_tests_tool=False,
                                                                           enable_guides=False)}
    timings = {}
    for workers in (1, 8):
        runner = EvalRunner(configs, model_spec=model, max_workers=workers, budget_usd=5.0)
        t0 = time.time()
        records = runner.run(tasks, RUNS / f"eval_w{workers}.jsonl")
        timings[workers] = round(time.time() - t0, 2)
    rows = summary_table(records)
    (RUNS / "eval_report.md").write_text("# Forge eval\n\n" + to_markdown(rows) + "\n")
    exported = export_task_dirs(tasks[:3], RUNS / "task_dirs")
    def outcomes(path):
        rows_ = [json.loads(line) for line in path.read_text().splitlines()]
        return sorted((r["config"], r["task_id"], r["trial"], r["success"], r["steps"]) for r in rows_)
    same = outcomes(RUNS / "eval_w1.jsonl") == outcomes(RUNS / "eval_w8.jsonl")
    return LabReport("25", "Eval harness architecture", "dataset -> environment -> runner -> graders -> reporter.",
                     {"seconds_1_worker": timings[1], "seconds_8_workers": timings[8],
                      "speedup": round(timings[1] / max(0.01, timings[8]), 2),
                      "results_identical_across_concurrency": same, "spent_usd": round(runner.spent, 4)},
                     rows, artifacts=["runs/eval_w8.jsonl", "runs/eval_w8.manifest.json", "runs/eval_report.md",
                                      *exported])


def main() -> None:
    a = lab_args(__doc__, seeds=1, n=40)
    finish(run(a.model, a.seeds, a.n), a.json)


if __name__ == "__main__":
    main()

"""Lab 8: redesign three bad tools and measure success before and after."""
from __future__ import annotations

from labs.common import LabReport, finish, lab_args, rate
from forge.config import HarnessConfig
from forge.loop import AgentLoop
from forge.models import make_model
from forge.tasks import dev_tasks

VARIANTS = {
    "bad tools (raw dumps, bare errors, full-suite output)": HarnessConfig(extra={"tool_style": "bad"}),
    "good tools (paged reads, actionable errors, focused tests)": HarnessConfig(extra={"tool_style": "good"}),
}


def run(model: str = "sim:small", seeds: int = 3, logs: int = 3) -> LabReport:
    rows = []
    for name, cfg in VARIANTS.items():
        ok, toks, steps, blind = [], [], [], 0
        for seed in range(seeds):
            for t in dev_tasks(distractors=logs):
                r = AgentLoop(make_model(model, seed), cfg).run(t)
                ok.append(r.success)
                toks.append(r.usage.input_tokens)
                steps.append(r.steps)
                calls = [c.signature() for m in r.messages if m.role == "assistant" for c in m.tool_calls]
                blind += sum(1 for a, b in zip(calls, calls[1:]) if a == b)     # identical back-to-back calls
        rows.append({"tools": name, "pass_rate": rate(ok), "mean_kTok": round(sum(toks) / len(toks) / 1000, 1),
                     "mean_steps": round(sum(steps) / len(steps), 2), "blind_retries": blind})
    return LabReport("08", "Tool redesign: before and after", f"Model {model}; {logs} build logs per task to "
                     "inflate context the way real investigations do.", {}, rows,
                     {"x": "tools", "y": ["pass_rate"], "kind": "bar"})


def main() -> None:
    a = lab_args(__doc__, model="sim:small", seeds=3, logs=3)
    finish(run(a.model, a.seeds, a.logs), a.json)


if __name__ == "__main__":
    main()

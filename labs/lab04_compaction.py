"""Lab 4: compaction strategies vs task length, plus cache-aware prompt layout."""
from __future__ import annotations

from labs.common import LabReport, finish, lab_args, rate
from forge.config import HarnessConfig
from forge.loop import AgentLoop
from forge.models import make_model
from forge.tasks import dev_tasks

STRATEGIES = ["none", "truncate", "compact", "offload"]


def run(model: str = "sim:small", seeds: int = 2, max_logs: int = 8) -> LabReport:
    rows = []
    for n_logs in range(0, max_logs + 1, 2):                  # task length = logs read before the fix
        tasks = dev_tasks(distractors=n_logs)[:10]
        row = {"logs_read": n_logs}
        for strategy in STRATEGIES:
            # Page size 16k chars: each log costs ~4k tokens, like a real CI log excerpt.
            cfg = HarnessConfig(compaction=strategy, compaction_threshold_tokens=9000, read_page_size=16000)
            ok, toks = [], []
            for seed in range(seeds):
                for t in tasks:
                    r = AgentLoop(make_model(model, seed), cfg).run(t)
                    ok.append(r.success)
                    toks.append(r.usage.input_tokens)
            row[f"{strategy}_pass"] = rate(ok)
            row[f"{strategy}_kTok"] = round(sum(toks) / len(toks) / 1000, 1)
        rows.append(row)

    # Cache-aware layout: identical run, stable prefix vs a timestamp at the top of the prompt.
    cache = {}
    for hostile in (False, True):
        m = make_model(model, 0)
        cached = total = 0
        for t in dev_tasks(distractors=2)[:10]:
            r = AgentLoop(m, HarnessConfig(), cache_hostile_prompt=hostile).run(t)
            cached += r.usage.cached_input_tokens
            total += r.usage.input_tokens
        cache["timestamp_first" if hostile else "stable_prefix_first"] = round(cached / max(1, total), 3)
    return LabReport("04", "Compaction vs task length", f"Model {model}; success and mean input tokens per run.",
                     {f"cache_hit_ratio[{k}]": v for k, v in cache.items()}, rows,
                     {"x": "logs_read", "y": [f"{s}_pass" for s in STRATEGIES], "kind": "line"})


def main() -> None:
    a = lab_args(__doc__, model="sim:small", seeds=2, max_logs=8)
    finish(run(a.model, a.seeds, a.max_logs), a.json)


if __name__ == "__main__":
    main()

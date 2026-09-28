"""Lab 22: chaos tests against Forge with a recovery scorecard."""
from __future__ import annotations

from labs.common import LabReport, finish, lab_args, rate
from forge.config import HarnessConfig
from forge.loop import AgentLoop
from forge.models import SimulatedModel
from forge.reliability import ChaosModel, ResilientModel, canary_gate
from forge.tasks import dev_tasks

FAULTS = {"none": (0.0, 0.0, 0.0), "provider 5xx 20%": (0.20, 0.0, 0.0),
          "malformed tool args 20%": (0.0, 0.20, 0.0), "empty completions 15%": (0.0, 0.0, 0.15),
          "all of the above": (0.15, 0.15, 0.10)}


def run(model: str = "sim:frontier", seeds: int = 2) -> LabReport:
    rows = []
    for fault, (err, bad, empty) in FAULTS.items():
        for resilient in (False, True):
            ok, statuses = [], []
            for seed in range(seeds):
                for i, t in enumerate(dev_tasks()):
                    chaos = ChaosModel(SimulatedModel(model.split(":")[-1], seed), err, bad, empty,
                                       seed=seed * 100 + i)
                    m = ResilientModel(chaos, retries=3) if resilient else chaos
                    r = AgentLoop(m, HarnessConfig()).run(t)
                    ok.append(r.success)
                    statuses.append(r.status)
            rows.append({"fault": fault, "retry+breaker": "on" if resilient else "off", "pass_rate": rate(ok),
                         "provider_errors": statuses.count("provider_error"),
                         "silent_empty_finishes": sum(s == "completed" and not o for s, o in zip(statuses, ok))})
    baseline = [True] * 34 + [False] * 6
    canary_bad = [True] * 14 + [False] * 6
    decision = canary_gate(baseline, canary_bad)
    return LabReport("22", "Chaos and recovery scorecard", "Faults injected at the model boundary; the harness "
                     "either absorbs them or turns them into clean, attributable failures.",
                     {"canary_decision": f"promote={decision.promote}: {decision.reason}"}, rows)


def main() -> None:
    a = lab_args(__doc__, seeds=2)
    finish(run(a.model, a.seeds), a.json)


if __name__ == "__main__":
    main()

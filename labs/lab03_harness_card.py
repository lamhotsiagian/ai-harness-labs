"""Lab 3: write a Harness Card for Forge v0, generated from code so it cannot drift."""
from __future__ import annotations

from labs.common import RUNS, LabReport, finish, lab_args
from forge.config import HarnessConfig
from forge.harness_card import forge_card
from forge.sandbox import Sandbox
from forge.tasks import cleanup, dev_tasks, prepare_workspace
from forge.toolkit import build_forge_tools


def run(model: str = "sim:frontier", seeds: int = 1) -> LabReport:
    cfg = HarnessConfig(name="forge-v0", version="0.1.0")
    ws = prepare_workspace(dev_tasks()[0])
    tools = build_forge_tools(Sandbox(ws), cfg)
    cleanup(ws)
    card = forge_card(cfg, tools.names())
    RUNS.mkdir(exist_ok=True)
    md, js = RUNS / "harness_card_forge_v0.md", RUNS / "harness_card_forge_v0.json"
    md.write_text(card.to_markdown())
    js.write_text(card.to_json())
    rows = [{"layer": k, "implementation": v[:90]} for k, v in card.layers.items()]
    return LabReport("03", "Harness Card for Forge v0", "Card regenerated from the live HarnessConfig and tool registry.",
                     {"fingerprint": card.fingerprint, "tools": len(tools.names())}, rows,
                     artifacts=["runs/harness_card_forge_v0.md", "runs/harness_card_forge_v0.json"])


def main() -> None:
    a = lab_args(__doc__, seeds=1)
    finish(run(a.model, a.seeds), a.json)


if __name__ == "__main__":
    main()

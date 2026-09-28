"""Lab 14: tear down reference harnesses with the seven-layer method and write a Harness Card."""
from __future__ import annotations

from labs.common import RUNS, LabReport, finish, lab_args
from forge.harness_card import LAYERS, REFERENCE_HARNESSES, HarnessCard


def run(model: str = "sim:frontier", seeds: int = 1, target: str = "mini-SWE-agent") -> LabReport:
    rows = [{"layer": layer, **{name: spec[layer][:38] for name, spec in list(REFERENCE_HARNESSES.items())[:4]}}
            for layer in LAYERS]
    spec = REFERENCE_HARNESSES[target]
    card = HarnessCard(target, "teardown", "n/a", "agent", "Solve issues in a repository with bash only.",
                       dict(spec), {"steps": "configurable"}, "container per task",
                       ["no structured tools: every action is a shell command",
                        "no policy layer beyond the container boundary"],
                       out_of_scope=["production write access"])
    RUNS.mkdir(exist_ok=True)
    out = RUNS / f"harness_card_{target.replace(' ', '_').replace('/', '_')}.md"
    out.write_text(card.to_markdown())
    matrix = RUNS / "seven_layer_matrix.md"
    names = list(REFERENCE_HARNESSES)
    matrix.write_text("| Layer | " + " | ".join(names) + " |\n|" + "---|" * (len(names) + 1) + "\n" + "\n".join(
        f"| {layer} | " + " | ".join(REFERENCE_HARNESSES[n][layer] for n in names) + " |" for layer in LAYERS) + "\n")
    return LabReport("14", "Seven-layer teardown", "Comparison matrix (first four harnesses shown; full matrix in the "
                     "artifact) and a Harness Card for the teardown target.", {"target": target}, rows,
                     artifacts=[str(out.relative_to(RUNS.parent)), str(matrix.relative_to(RUNS.parent))])


def main() -> None:
    a = lab_args(__doc__, seeds=1, target="mini-SWE-agent")
    finish(run(a.model, a.seeds, a.target), a.json)


if __name__ == "__main__":
    main()

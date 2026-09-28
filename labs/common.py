"""Shared plumbing for labs: a uniform report that the CLI and the Streamlit UI both render."""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RUNS = ROOT / "runs"
sys.path.insert(0, str(ROOT))


@dataclass
class LabReport:
    lab: str
    title: str
    summary: str
    metrics: dict = field(default_factory=dict)
    table: list[dict] = field(default_factory=list)
    chart: dict | None = None            # {"x": "col", "y": ["col", ...], "kind": "line"|"bar"}
    artifacts: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def print(self) -> None:
        bar = "=" * 78
        print(f"{bar}\nLab {self.lab}: {self.title}\n{bar}\n{self.summary}\n")
        for k, v in self.metrics.items():
            print(f"  {k:<34} {v}")
        if self.table:
            cols = list(self.table[0])
            widths = {c: max(len(str(c)), *(len(str(r.get(c, ""))) for r in self.table)) for c in cols}
            print()
            print("  " + "  ".join(str(c).ljust(widths[c]) for c in cols))
            print("  " + "  ".join("-" * widths[c] for c in cols))
            for r in self.table:
                print("  " + "  ".join(str(r.get(c, "")).ljust(widths[c]) for c in cols))
        for n in self.notes:
            print(f"\n  note: {n}")
        for a in self.artifacts:
            print(f"  artifact: {a}")
        print()

    def save(self) -> Path:
        RUNS.mkdir(exist_ok=True)
        path = RUNS / f"lab{self.lab}_report.json"
        path.write_text(json.dumps(asdict(self), indent=1, default=str))
        return path


def lab_args(description: str, **defaults) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=description)
    p.add_argument("--model", default=defaults.get("model", "sim:frontier"),
                   help="sim:frontier | sim:small | sim:open-weight | anthropic:<id> | openai:<id>")
    p.add_argument("--seeds", type=int, default=defaults.get("seeds", 3))
    p.add_argument("--json", action="store_true", help="print the report as JSON")
    def str2bool(v: str) -> bool:
        return str(v).lower() in ("1", "true", "yes", "on")

    for key, value in defaults.items():
        if key not in ("model", "seeds"):
            kind = str2bool if isinstance(value, bool) else type(value)
            p.add_argument(f"--{key.replace('_', '-')}", type=kind, default=value)
    return p.parse_args()


def finish(report: LabReport, as_json: bool = False) -> LabReport:
    path = report.save()
    report.artifacts.append(str(path.relative_to(ROOT)))
    if as_json:
        print(json.dumps(asdict(report), indent=1, default=str))
    else:
        report.print()
    return report


def rate(xs) -> float:
    xs = list(xs)
    return round(sum(xs) / len(xs), 3) if xs else 0.0

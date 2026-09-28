"""CLI: python -m forgeapp.pipeline_lint_cli  -> exit 1 when .forge/pipeline.yaml violates policy."""
import sys
from pathlib import Path

from forgeapp.pipeline_lint import lint_stages


def load_stages(path: Path) -> list[dict]:
    stages, current = [], None
    for line in path.read_text().splitlines():
        s = line.strip()
        if s.startswith("- name:"):
            current = {"name": s.split(":", 1)[1].strip()}
            stages.append(current)
        elif current is not None and ":" in s and not s.startswith("name:"):
            k, v = s.split(":", 1)
            current[k.strip()] = v.strip()
    return stages


if __name__ == "__main__":
    problems = lint_stages(load_stages(Path(".forge/pipeline.yaml")))
    for p in problems:
        print(f"violation: {p}")
    print("pipeline OK" if not problems else f"{len(problems)} violation(s)")
    sys.exit(1 if problems else 0)

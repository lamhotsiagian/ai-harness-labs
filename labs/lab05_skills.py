"""Lab 5: build three Skills and measure selection accuracy and disclosure cost."""
from __future__ import annotations

import json

from labs.common import ROOT, LabReport, finish, lab_args
from forge.messages import estimate_tokens
from forge.skills import SkillSelector, load_skills, skill_index


def run(model: str = "sim:frontier", seeds: int = 1) -> LabReport:
    queries = json.loads((ROOT / "fixtures" / "skill_queries.json").read_text())
    rows, confusion = [], {}
    for vague in (False, True):
        skills = load_skills(vague=vague)
        selector = SkillSelector(skills)
        correct = 0
        for query, gold in queries:
            chosen = selector.select(query)
            name = chosen.name if chosen else "none"
            correct += name == gold
            if not vague:
                confusion.setdefault(gold, {}).setdefault(name, 0)
                confusion[gold][name] += 1
        rows.append({"descriptions": "vague" if vague else "specific", "accuracy": round(correct / len(queries), 3),
                     "n": len(queries)})
    skills = load_skills()
    index_tokens = estimate_tokens(skill_index(skills))
    eager_tokens = sum(estimate_tokens(s.body) for s in skills) + index_tokens
    return LabReport("05", "Skill selection accuracy", "Selection is only as good as the description the model reads.",
                     {"index_tokens (progressive)": index_tokens, "all_bodies_tokens (eager)": eager_tokens,
                      "projected_100_skills_progressive": index_tokens * 100 // len(skills),
                      "projected_100_skills_eager": eager_tokens * 100 // len(skills),
                      "confusion (specific)": json.dumps(confusion)}, rows,
                     {"x": "descriptions", "y": ["accuracy"], "kind": "bar"})


def main() -> None:
    a = lab_args(__doc__, seeds=1)
    finish(run(a.model, a.seeds), a.json)


if __name__ == "__main__":
    main()

"""Skills: versioned, discoverable procedural knowledge (Chapter 5).

Progressive disclosure: the system prompt carries only each Skill's name and
one-line description (tens of tokens). The full body loads only when a Skill is
selected, so a catalogue of 100 Skills costs almost nothing until it is used.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from .retrieval import BM25

SKILLS_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "skills"


@dataclass
class Skill:
    name: str
    description: str
    body: str
    path: Path
    meta: dict = field(default_factory=dict)

    def index_line(self) -> str:
        return f"- {self.name}: {self.description}"


def parse_frontmatter(text: str) -> tuple[dict, str]:
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.S)
    if not m:
        return {}, text
    meta = {}
    for line in m.group(1).splitlines():
        key, _, value = line.partition(":")
        value = value.strip()
        if value.startswith("[") and value.endswith("]"):
            meta[key.strip()] = [v.strip() for v in value[1:-1].split(",") if v.strip()]
        else:
            meta[key.strip()] = value
    return meta, m.group(2)


def load_skills(root: Path = SKILLS_DIR, vague: bool = False) -> list[Skill]:
    skills = []
    for f in sorted(root.glob("*/SKILL.md")):
        meta, body = parse_frontmatter(f.read_text())
        desc = meta.get("vague_description" if vague else "description", "")
        skills.append(Skill(meta["name"], desc, body.strip(), f, meta))
    return skills


def skill_index(skills: list[Skill]) -> str:
    """The only Skill text that lives in every prompt."""
    return "## Available Skills (load on demand)\n" + "\n".join(s.index_line() for s in skills)


class SkillSelector:
    """Lexical selector over descriptions, a stand-in for the model's own choice.

    Selection quality is dominated by description quality, which is exactly the
    property Lab 5 measures: vague descriptions give the selector nothing to match.
    """

    def __init__(self, skills: list[Skill], threshold: float = 0.1):
        self.skills = skills
        self.bm25 = BM25([s.name.replace("-", " ") + " " + s.description for s in skills])
        self.threshold = threshold

    def select(self, query: str) -> Skill | None:
        scores = self.bm25.scores(query)
        best = max(range(len(scores)), key=lambda i: scores[i])
        return self.skills[best] if scores[best] > self.threshold else None

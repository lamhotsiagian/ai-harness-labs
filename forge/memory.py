"""Memory for agents: progress ledgers, episodic lessons, and provenance (Chapter 6).

* ProgressLedger  - the TODO/progress file that lets a fresh session resume work.
* EpisodicStore   - lessons learned across runs, with provenance, TTL, and
                    re-validation, because unvalidated memory is a poisoning vector.
"""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass
class LedgerItem:
    id: str
    title: str
    status: str = "todo"             # todo | in_progress | done | blocked
    attempts: int = 0
    evidence: str = ""


@dataclass
class ProgressLedger:
    """JSON source of truth plus a human-readable Markdown mirror."""
    path: Path
    items: list[LedgerItem] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @classmethod
    def load(cls, path: Path) -> "ProgressLedger":
        if not path.exists():
            return cls(path)
        data = json.loads(path.read_text())
        return cls(path, [LedgerItem(**i) for i in data["items"]], data.get("notes", []))

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"items": [asdict(i) for i in self.items], "notes": self.notes}, indent=1))
        tmp.replace(self.path)                       # atomic: a crash never leaves half a file
        md = ["# Progress", ""] + [f"- [{'x' if i.status == 'done' else ' '}] {i.id}: {i.title} "
                                   f"({i.status}, attempts={i.attempts}) {i.evidence}" for i in self.items]
        md += ["", "## Notes"] + [f"- {n}" for n in self.notes[-20:]]
        self.path.with_suffix(".md").write_text("\n".join(md) + "\n")

    def next_open(self) -> LedgerItem | None:
        for status in ("in_progress", "todo"):
            for item in self.items:
                if item.status == status:
                    return item
        return None

    def mark(self, item_id: str, status: str, evidence: str = "") -> None:
        for item in self.items:
            if item.id == item_id:
                item.status = status
                item.evidence = evidence or item.evidence
                if status == "in_progress":
                    item.attempts += 1
        self.save()

    def as_context(self) -> str:
        """Compact text a new session reads first (tens of tokens, not the whole history)."""
        done = sum(i.status == "done" for i in self.items)
        nxt = self.next_open()
        return (f"Progress: {done}/{len(self.items)} done. Next: {nxt.id if nxt else 'none'}. "
                f"Last notes: {' | '.join(self.notes[-3:])}")


@dataclass
class Lesson:
    text: str
    source: str                      # run id or human reviewer that produced it
    trust: str                       # human | verified_run | unverified
    created: float
    ttl_days: float = 30
    uses: int = 0
    wins: int = 0

    @property
    def key(self) -> str:
        return hashlib.sha256(self.text.encode()).hexdigest()[:10]

    def expired(self, now: float | None = None) -> bool:
        return ((now or time.time()) - self.created) > self.ttl_days * 86400


class EpisodicStore:
    """Append-only JSONL of lessons with a write gate against poisoning."""

    def __init__(self, path: Path):
        self.path = path
        self.lessons: dict[str, Lesson] = {}
        if path.exists():
            for line in path.read_text().splitlines():
                lesson = Lesson(**json.loads(line))
                self.lessons[lesson.key] = lesson

    def write(self, text: str, source: str, trust: str) -> bool:
        # Write gate: untrusted sources (tool output, web pages) never become memory directly.
        if trust == "unverified" or any(w in text.lower() for w in ("ignore previous", "always approve")):
            return False
        lesson = Lesson(text, source, trust, time.time())
        self.lessons[lesson.key] = lesson
        with self.path.open("a") as fh:
            fh.write(json.dumps(asdict(lesson)) + "\n")
        return True

    def recall(self, k: int = 3, now: float | None = None) -> list[Lesson]:
        live = [l for l in self.lessons.values() if not l.expired(now)]
        # Rank by observed usefulness; unproven lessons get a neutral prior.
        return sorted(live, key=lambda l: -((l.wins + 1) / (l.uses + 2)))[:k]

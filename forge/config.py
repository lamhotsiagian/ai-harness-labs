"""Harness configuration: every knob a lab or an ablation can turn.

The configuration fingerprint is written into every trace span and every eval
report, so a result can always be traced back to the exact harness that
produced it (Chapters 20 and 26).
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field

HARNESS_VERSION = "forge-1.0.0"


@dataclass
class Budgets:
    max_steps: int = 24            # model calls per run
    max_tokens: int = 250_000      # cumulative input + output tokens
    max_cost_usd: float = 2.00     # hard spend ceiling per run
    max_wall_seconds: float = 120  # wall-clock ceiling per run


@dataclass
class HarnessConfig:
    name: str = "forge"
    version: str = HARNESS_VERSION
    budgets: Budgets = field(default_factory=Budgets)
    permission_mode: str = "auto"          # read_only | ask | auto
    enable_tests_tool: bool = True         # computational sensor available
    enable_feedback: bool = True           # sensor detail returned to the model
    enable_guides: bool = True             # AGENTS.md injected as feedforward guide
    spotlighting: bool = True              # untrusted content wrapped in markers
    compaction: str = "none"               # none | truncate | compact | offload
    compaction_threshold_tokens: int = 12_000
    loop_detection: bool = True
    repeat_limit: int = 3                  # identical tool calls before intervention
    egress_allowlist: list[str] = field(default_factory=lambda: ["pypi.org", "github.com"])
    protect_tests: bool = False            # hook: block edits under tests/
    read_page_size: int = 4000             # characters returned per read_file page
    extra: dict = field(default_factory=dict)

    def fingerprint(self) -> str:
        """Short content hash of the full configuration."""
        blob = json.dumps(asdict(self), sort_keys=True, default=str)
        return hashlib.sha256(blob.encode()).hexdigest()[:12]

    def to_dict(self) -> dict:
        d = asdict(self)
        d["fingerprint"] = self.fingerprint()
        return d

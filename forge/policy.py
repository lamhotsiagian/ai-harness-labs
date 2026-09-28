"""Policy layer: permission modes, approvals, guardrails, and the lethal trifecta.

Every tool call passes through `PolicyEngine.check` before execution. The engine
knows only the tool's declared side-effect class and the session's risk state,
so new tools inherit the policy without new code (Chapters 11, 18, 19).
"""
from __future__ import annotations

import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Callable

from .tools import ToolSpec

INJECTION_PATTERNS = [
    r"ignore (all |any )?(previous|prior|above) instructions",
    r"AGENT-INSTRUCTION",
    r"you are now",
    r"system prompt",
    r"exfiltrat",
    r"(send|post|upload) .{0,40}(token|secret|\.env|credential)",
]
SECRET_PATTERNS = {
    "canary": r"forge-canary-[0-9a-f]{6}",
    "aws_key": r"AKIA[0-9A-Z]{16}",
    "bearer": r"(?i)bearer\s+[a-z0-9\-_\.]{20,}",
    "email": r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",
}


def injection_score(text: str) -> tuple[float, list[str]]:
    hits = [p for p in INJECTION_PATTERNS if re.search(p, text, re.I)]
    return min(1.0, 0.4 * len(hits)), hits


def redact(text: str) -> tuple[str, list[str]]:
    found = []
    for name, pattern in SECRET_PATTERNS.items():
        if re.search(pattern, text):
            found.append(name)
            text = re.sub(pattern, f"[REDACTED:{name}]", text)
    return text, found


@dataclass
class ApprovalRequest:
    id: str
    tool: str
    args: dict
    reason: str
    created: float
    status: str = "pending"            # pending | approved | denied | expired
    decided_by: str = ""


class ApprovalQueue:
    """Human-in-the-loop queue with a timeout that fails closed."""

    def __init__(self, timeout_s: float = 300.0):
        self.items: dict[str, ApprovalRequest] = {}
        self.timeout_s = timeout_s
        self.lock = threading.Lock()

    def submit(self, tool: str, args: dict, reason: str) -> ApprovalRequest:
        req = ApprovalRequest(uuid.uuid4().hex[:8], tool, args, reason, time.time())
        with self.lock:
            self.items[req.id] = req
        return req

    def decide(self, req_id: str, approve: bool, who: str = "human") -> None:
        with self.lock:
            req = self.items[req_id]
            req.status, req.decided_by = ("approved" if approve else "denied"), who

    def pending(self) -> list[ApprovalRequest]:
        now = time.time()
        with self.lock:
            for r in self.items.values():
                if r.status == "pending" and now - r.created > self.timeout_s:
                    r.status = "expired"      # fail closed
            return [r for r in self.items.values() if r.status == "pending"]


@dataclass
class SessionRisk:
    """Tracks the three legs of the lethal trifecta for one session."""
    private_data: bool = False
    untrusted_content: bool = False
    exfil_attempts: int = 0


@dataclass
class PolicyDecision:
    allowed: bool
    reason: str = ""
    needs_approval: bool = False


@dataclass
class PolicyEngine:
    mode: str = "auto"                                   # read_only | ask | auto
    approver: Callable[[str, dict, str], bool] | None = None
    block_trifecta: bool = True
    private_globs: tuple[str, ...] = (".env", "secrets/")
    risk: SessionRisk = field(default_factory=SessionRisk)
    log: list[dict] = field(default_factory=list)

    def observe(self, tool: str, args: dict, untrusted: bool) -> None:
        path = str(args.get("path", ""))
        if tool == "read_file" and any(path.startswith(g) for g in self.private_globs):
            self.risk.private_data = True
        if untrusted:
            self.risk.untrusted_content = True

    def check(self, spec: ToolSpec, args: dict) -> PolicyDecision:
        decision = self._decide(spec, args)
        self.log.append({"tool": spec.name, "allowed": decision.allowed, "reason": decision.reason})
        return decision

    def _decide(self, spec: ToolSpec, args: dict) -> PolicyDecision:
        if self.mode == "read_only" and spec.side_effect != "read":
            return PolicyDecision(False, "read_only mode: writes and external calls are disabled")
        if spec.side_effect == "external":
            self.risk.exfil_attempts += 1
            if self.block_trifecta and self.risk.private_data and self.risk.untrusted_content:
                return PolicyDecision(False, "lethal trifecta: private data + untrusted content + egress")
        needs = spec.requires_approval or (self.mode == "ask" and spec.side_effect != "read")
        if needs:
            if self.approver is None:
                return PolicyDecision(False, "approval required but no approver configured", True)
            ok = self.approver(spec.name, args, "policy")
            return PolicyDecision(ok, "approved by human" if ok else "denied by human", True)
        return PolicyDecision(True)

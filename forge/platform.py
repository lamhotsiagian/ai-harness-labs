"""Governed pipeline changes: plan -> dry run -> approval -> apply -> audit (Chapter 10).

This is the platform-integration pattern from the Harness MCP chapter reduced to
its essentials: the agent may *propose* pipeline changes; only an approved
change is applied; every step lands in an append-only audit log.
"""
from __future__ import annotations

import copy
import difflib
import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from .policy import ApprovalQueue

PIPELINE_SCHEMA_VERSION = "2026-09"


def parse_pipeline(text: str) -> dict:
    """Parser for the restricted pipeline YAML subset used by forgeapp-ci."""
    doc: dict = {"stages": []}
    current = None
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line or line.lstrip().startswith("#"):
            continue
        if line.startswith("name:"):
            doc["name"] = line.split(":", 1)[1].strip()
        elif line.strip().startswith("- name:"):
            current = {"name": line.split(":", 1)[1].strip()}
            doc["stages"].append(current)
        elif current is not None and ":" in line:
            key, value = line.strip().split(":", 1)
            current[key.strip()] = value.strip()
    return doc


def dump_pipeline(doc: dict) -> str:
    out = [f"name: {doc.get('name', 'pipeline')}", "stages:"]
    for stage in doc["stages"]:
        out.append(f"  - name: {stage['name']}")
        for k, v in stage.items():
            if k != "name":
                out.append(f"    {k}: {v}")
    return "\n".join(out) + "\n"


def lint(doc: dict) -> list[str]:
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "fixtures" / "sample_repo"))
    from forgeapp.pipeline_lint import lint_stages  # the repo's own linter is the sensor
    return lint_stages(doc["stages"])


def plan_change(request: str, doc: dict) -> dict:
    """Deterministic stand-in for the model's structured plan (a JSON patch-like op)."""
    r = request.lower()
    m = re.search(r"add (?:a |an )?(\w[\w-]*) stage (before|after) (?:the )?(\w+)", r)
    if m:
        name, where, anchor = m.groups()
        return {"op": "insert", "stage": {"name": name, "run": f"make {name}"}, "where": where, "anchor": anchor}
    m = re.search(r"remove (?:the )?(\w+) stage", r)
    if m:
        return {"op": "remove", "name": m.group(1)}
    if "skip approval" in r or "without approval" in r or "remove approval" in r:
        return {"op": "set", "name": "deploy", "key": "approval", "value": "none"}
    m = re.search(r"move (?:the )?(\w+) (?:stage )?(before|after) (?:the )?(\w+)", r)
    if m:
        return {"op": "move", "name": m.group(1), "where": m.group(2), "anchor": m.group(3)}
    return {"op": "noop", "reason": "request not understood; ask a clarifying question"}


def apply_plan(doc: dict, plan: dict) -> dict:
    new = copy.deepcopy(doc)
    names = [s["name"] for s in new["stages"]]
    if plan["op"] == "insert":
        idx = names.index(plan["anchor"]) + (1 if plan["where"] == "after" else 0)
        new["stages"].insert(idx, plan["stage"])
    elif plan["op"] == "remove":
        new["stages"] = [s for s in new["stages"] if s["name"] != plan["name"]]
    elif plan["op"] == "set":
        for s in new["stages"]:
            if s["name"] == plan["name"]:
                s[plan["key"]] = plan["value"]
    elif plan["op"] == "move":
        stage = new["stages"].pop(names.index(plan["name"]))
        names = [s["name"] for s in new["stages"]]
        idx = names.index(plan["anchor"]) + (1 if plan["where"] == "after" else 0)
        new["stages"].insert(idx, stage)
    return new


@dataclass
class GovernedPipelineService:
    pipeline_path: Path
    audit_path: Path
    queue: ApprovalQueue = field(default_factory=ApprovalQueue)
    proposals: dict = field(default_factory=dict)

    def _audit(self, event: str, **data) -> None:
        self.audit_path.parent.mkdir(parents=True, exist_ok=True)
        with self.audit_path.open("a") as fh:
            fh.write(json.dumps({"ts": time.time(), "event": event, **data}) + "\n")

    def propose(self, request: str, principal: str) -> dict:
        before_text = self.pipeline_path.read_text()
        before = parse_pipeline(before_text)
        plan = plan_change(request, before)
        if plan["op"] == "noop":
            self._audit("rejected_plan", principal=principal, request=request, reason=plan["reason"])
            return {"status": "needs_clarification", "plan": plan}
        after = apply_plan(before, plan)
        problems = lint(after)                     # dry run: the change is validated, not applied
        diff = "".join(difflib.unified_diff(before_text.splitlines(True), dump_pipeline(after).splitlines(True),
                                            "pipeline.yaml (current)", "pipeline.yaml (proposed)"))
        if problems:
            self._audit("dry_run_failed", principal=principal, request=request, problems=problems)
            return {"status": "rejected", "problems": problems, "diff": diff}
        req = self.queue.submit("apply_pipeline_change", {"plan": plan}, f"{principal}: {request}")
        self.proposals[req.id] = {"after": after, "diff": diff, "principal": principal, "request": request}
        self._audit("proposed", principal=principal, request=request, approval_id=req.id, diff=diff)
        return {"status": "pending_approval", "approval_id": req.id, "diff": diff}

    def decide(self, approval_id: str, approve: bool, approver: str) -> dict:
        prop = self.proposals[approval_id]
        if approver == prop["principal"]:
            self._audit("self_approval_blocked", approver=approver, approval_id=approval_id)
            return {"status": "denied", "reason": "requester cannot approve their own change"}
        self.queue.decide(approval_id, approve, approver)
        if not approve:
            self._audit("denied", approver=approver, approval_id=approval_id)
            return {"status": "denied"}
        self.pipeline_path.write_text(dump_pipeline(prop["after"]))
        self._audit("applied", approver=approver, approval_id=approval_id)
        return {"status": "applied"}


# ----------------------------------------------------- integration contract tests
TOOL_CONTRACT = {
    "propose_pipeline_change": {"required": ["request", "principal"], "version": PIPELINE_SCHEMA_VERSION},
    "decide_pipeline_change": {"required": ["approval_id", "approve", "approver"], "version": PIPELINE_SCHEMA_VERSION},
}


def contract_diff(old: dict, new: dict) -> list[str]:
    """Breaking-change detector for a platform MCP integration (semver discipline)."""
    breaks = []
    for name, spec in old.items():
        if name not in new:
            breaks.append(f"removed tool {name}")
            continue
        added_required = set(new[name]["required"]) - set(spec["required"])
        if added_required:
            breaks.append(f"{name}: new required fields {sorted(added_required)}")
    return breaks

"""Lab 19: a governance scorecard for Forge (identity, change control, audit, egress, kill switch)."""
from __future__ import annotations

from dataclasses import dataclass

from labs.common import LabReport, finish, lab_args
from forge.config import HarnessConfig


@dataclass
class Deployment:
    """What a governance review actually inspects: config plus operating facts."""
    config: HarnessConfig
    agent_principal: str | None              # non-human identity, not a shared user token
    credential_ttl_minutes: int | None       # delegated, short-lived credentials
    approved_fingerprints: set[str]          # change control for prompts/Skills/hooks/harness
    audit_sink: str | None                   # e.g. SIEM topic
    trace_retention_days: int
    data_region: str
    allowed_regions: set[str]
    kill_switch: bool
    incident_runbook: bool
    human_approval_for_prod: bool


CONTROLS = [
    # (id, weight, description, check)
    ("ID-1", 10, "agent runs as its own non-human principal", lambda d: bool(d.agent_principal)),
    ("ID-2", 10, "credentials are delegated and expire within 60 minutes",
     lambda d: d.credential_ttl_minutes is not None and d.credential_ttl_minutes <= 60),
    ("CC-1", 15, "running harness fingerprint is on the approved list",
     lambda d: d.config.fingerprint() in d.approved_fingerprints),
    ("AU-1", 10, "every tool call is exported to an audit sink", lambda d: bool(d.audit_sink)),
    ("AU-2", 5, "traces retained >= 30 days", lambda d: d.trace_retention_days >= 30),
    ("EG-1", 10, "egress is an allowlist, not open", lambda d: "*" not in d.config.egress_allowlist),
    ("DR-1", 10, "data stays in an allowed region", lambda d: d.data_region in d.allowed_regions),
    ("AP-1", 10, "production writes need human approval", lambda d: d.human_approval_for_prod),
    ("PM-1", 5, "permission mode is not auto for prod", lambda d: d.config.permission_mode != "auto"),
    ("OP-1", 10, "kill switch wired to every running agent", lambda d: d.kill_switch),
    ("OP-2", 5, "incident runbook covers agent-caused incidents", lambda d: d.incident_runbook),
]


def scorecard(d: Deployment) -> tuple[int, list[dict]]:
    rows, score = [], 0
    for cid, weight, text, check in CONTROLS:
        ok = bool(check(d))
        score += weight if ok else 0
        rows.append({"control": cid, "weight": weight, "requirement": text, "pass": ok})
    return score, rows


def run(model: str = "sim:frontier", seeds: int = 1) -> LabReport:
    pilot_cfg = HarnessConfig(egress_allowlist=["*"])
    pilot = Deployment(pilot_cfg, None, None, set(), None, 7, "us-east-1", {"ap-southeast-3"}, False, False, False)
    ent_cfg = HarnessConfig(permission_mode="ask", egress_allowlist=["pypi.org", "github.com"])
    enterprise = Deployment(ent_cfg, "svc-forge-agent@prod", 30, {ent_cfg.fingerprint()}, "siem://agents/forge",
                            90, "ap-southeast-3", {"ap-southeast-3"}, True, True, True)
    s1, r1 = scorecard(pilot)
    s2, r2 = scorecard(enterprise)
    rows = [{"control": a["control"], "requirement": a["requirement"], "weight": a["weight"],
             "pilot": "PASS" if a["pass"] else "FAIL", "enterprise": "PASS" if b["pass"] else "FAIL"}
            for a, b in zip(r1, r2)]
    drift = HarnessConfig(permission_mode="ask", egress_allowlist=["pypi.org", "github.com"], compaction="compact")
    enterprise.config = drift
    s3, _ = scorecard(enterprise)
    return LabReport("19", "Governance scorecard", "Weighted controls, scored from config and operating facts.",
                     {"pilot_score": f"{s1}/100", "enterprise_score": f"{s2}/100",
                      "enterprise_after_unreviewed_change": f"{s3}/100 (CC-1 fails: fingerprint not approved)"}, rows)


def main() -> None:
    a = lab_args(__doc__, seeds=1)
    finish(run(a.model, a.seeds), a.json)


if __name__ == "__main__":
    main()

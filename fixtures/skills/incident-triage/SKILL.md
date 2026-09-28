---
name: incident-triage
description: Investigate a production incident, outage, page, alert, latency spike, timeout, stall, or 5xx error-rate increase from logs and runbooks, then summarize root cause, impact, and actions with citations. Use for on-call and postmortem questions.
vague_description: Helps with operations.
triggers: [incident, outage, alert, latency, error rate, page, on-call, 5xx, runbook]
---
# SKILL:triage
1. Pull the alert and the matching runbook section.
2. Correlate the first bad deploy with the error onset.
3. Cite every claim with the source document id.
4. Recommend rollback only when the correlation is explicit.

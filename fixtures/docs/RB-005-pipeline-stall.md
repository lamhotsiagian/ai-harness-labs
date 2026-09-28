# RB-005 Runbook: release pipeline stalled
Symptom: pipeline waits in deploy for hours.
Most common cause: approval request unanswered; approvals time out after 4 hours and fail closed.
Second cause: semver comparison gate blocking because version compare is lexical (1.10.0 < 1.9.0).
Mitigation: page the release captain; verify forgeapp/semver.py compare uses numeric tuples.

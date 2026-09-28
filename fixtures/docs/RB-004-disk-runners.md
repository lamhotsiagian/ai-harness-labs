# RB-004 Runbook: build runner disk usage
Symptom: disk usage alert above 90 percent on CI runners; builds fail with "no space left on device".
Check: stale workspaces under /var/ci/ws, docker image cache, logs/ directories.
Mitigation: prune images older than 7 days; delete finished workspaces; rotate build logs.

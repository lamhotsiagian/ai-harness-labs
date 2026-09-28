# RB-002 Runbook: database connection pool exhaustion
Service: checkout. Owner: payments-core.
Symptom: checkout latency p99 above 3s, "pool timeout" errors, 5xx on payments API.
Check: connection pool metrics `db.pool.in_use`; long transactions; retry storms from backoff misconfiguration.
Mitigation: cap retries (see forgeapp/retry.py backoff cap), recycle pods, raise pool size by 20 percent.

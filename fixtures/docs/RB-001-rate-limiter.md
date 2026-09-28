# RB-001 Runbook: rate limiter rejecting all traffic
Service: public-api. Owner: platform-edge.
Symptom: 429 responses for every client; token bucket never refills.
Check: `forgeapp/ratelimit.py` TokenBucket.allow refill arithmetic; deploy diff for ratelimit.
Mitigation: roll back the last public-api deploy; raise capacity via feature flag RL_CAPACITY.
Escalate to platform-edge if 429 rate stays above 5 percent for 10 minutes.

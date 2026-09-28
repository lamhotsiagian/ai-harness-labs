---
name: bugfix-python
description: Fix a failing unit test or functional bug in a forgeapp Python module (pricing, slugify, semver, retry, inventory, textstats, ratelimit tokens bucket, envparse, dates business days). Use when an issue reports wrong output, a crash, a regression, or red CI tests.
vague_description: Helps with code.
triggers: [bug, wrong, fails, exception, regression, returns, test]
---
# SKILL:bugfix
1. Read the module named in the issue (`forgeapp/<module>.py`).
2. Reproduce with `run_tests(module=...)` before editing when the cause is unclear.
3. Patch the smallest expression that explains the symptom.
4. Run the module tests. Never edit `tests/`.
5. Report DONE with the failing-then-passing evidence.

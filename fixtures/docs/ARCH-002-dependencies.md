# ARCH-002 Dependency graph
checkout depends on pricing (discount, tax), inventory (reserve), retry (backoff).
release depends on semver (bump, compare) and dates (business days).
Changes to retry affect every service that calls payments-core.

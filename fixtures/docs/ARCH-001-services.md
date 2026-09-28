# ARCH-001 Service map
public-api -> ratelimit -> checkout -> payments-core -> postgres.
release pipeline: forgeapp-ci stages build, test, deploy (approval required).
Owners: platform-edge (public-api, ratelimit), payments-core (checkout, payments), release-eng (pipeline).

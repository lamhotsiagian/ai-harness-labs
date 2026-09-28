# RB-003 Runbook: rolling back a bad deploy
Applies to all services deployed through forgeapp-ci.
Steps: identify the deploy id from the release channel; run the rollback pipeline with approval; confirm error rate recovery within 15 minutes.
Deploy stages must keep `approval: required`. Never skip the test stage to speed up a rollback.

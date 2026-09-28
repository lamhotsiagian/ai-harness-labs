---
name: pipeline-edit
description: Change the CI/CD pipeline definition in .forge/pipeline.yaml: add, remove, rename, split, or reorder build, test, lint, scan, and deploy stages, or gate deploy on approval. Use for any pipeline yaml or CI stage request.
vague_description: Helps with pipelines.
triggers: [pipeline, stage, deploy, ci, approval, yaml, build, lint]
---
# SKILL:pipeline
1. Read `.forge/pipeline.yaml` and restate the requested change as a diff.
2. Keep `deploy` after `test` and keep `approval: required` on deploy.
3. Validate with `pipeline_lint.lint_stages` (dry run) before proposing.
4. Submit the change through the approval gate; never apply it directly.

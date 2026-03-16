# SentinelFetal2 Copilot Instructions (Migration Routing)

This file is intentionally minimal.

- This repository includes a **uv migration pack** for pip/requirements → uv/pyproject/uv.lock workflows.
- For migration tasks, use the dedicated migration stack:
  - custom agent: `.github/agents/uv-migration-architect.agent.md`
  - orchestrator instructions: `.github/instructions/uv-migration-orchestrator.instructions.md`
  - execution rules: `.github/instructions/uv-migration.instructions.md`
  - docker safety: `.github/instructions/docker-uv-cpu-torch.instructions.md`
  - dependency bucketing: `.github/instructions/dependency-classification.instructions.md`
- Migration policy is **not** the default policy for unrelated repository work.
- Outside uv migration workflows, do not treat migration-specific constraints as global repository governance.

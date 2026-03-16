---
description: 'Migration-only orchestration for SentinelFetal2 pip/requirements to uv transition.'
applyTo: 'pyproject.toml,uv.lock,requirements.txt,README.md,docs/**/*.md,Dockerfile,docker-compose.yml,.github/**/*.md,scripts/**/*.py,api/**/*.py,src/**/*.py'
---

# UV migration orchestrator (migration-only)

## Scope
This file orchestrates **only** the uv migration workflow for this repository.
It is not a general long-term policy for unrelated repository tasks.

## Always-active constraints
- Run migration work on a **dedicated non-default branch** only.
- Treat `pyproject.toml` + `uv.lock` as the final dependency authority.
- Run dependency resolution, sync, smoke checks, imports, and runtime verification in a **virtual environment only**.
- Dockerfiles may be updated during migration, but Docker is not an allowed environment for install/validation workflow execution.

## Orchestration order
1. Scope + branch guard
2. Inventory + dependency bucketing
3. Python baseline decision (newest safe legal minor)
4. uv-native migration edits
5. Verification gates in virtual environment
6. Visual validation (if browser tools are available)
7. Final report with blocked-state classification

## Loading strategy (hybrid)
- At run start: perform one baseline read of `/.github/UV_MIGRATION_PACK.md` and mapped core migration resources.
- Build one full dependency-aware plan from this baseline.
- During execution: use targeted stage-specific reads only.
- Re-open `/.github/UV_MIGRATION_PACK.md` only for ambiguity/conflict resolution.

## Pack component routing
- Execution policy: `.github/instructions/uv-migration.instructions.md`
- Docker safety policy: `.github/instructions/docker-uv-cpu-torch.instructions.md`
- Dependency bucketing: `.github/instructions/dependency-classification.instructions.md`
- Custom migration agent: `.github/agents/uv-migration-architect.agent.md`
- Reusable execution prompt: `.github/prompts/uv-migration-execution.prompt.md`
- Final checklist skill: `.github/skills/uv-migration-checklist/SKILL.md`

## Prompt/skill behavior rule
If a dedicated prompt file or skill applies to the current task/subtask, stop and inspect it before acting.
If it cannot be read/accessed, explicitly report that and continue using this orchestrator + core migration rules only.

## Reporting contract linkage
Final outputs must include:
- `Actively Followed`, `Consulted`, and `Known but Unused` pack components
- per-gate status: `Passed`, `Blocked`, or `Skipped (with reason)`
- completed edits vs unverified assumptions
- exact blocked items and required user actions

## Notes as source of truth
When working notes exist under `.github/migration-notes/`, maintain them continuously during execution and use them as primary source material for final reporting.
Clarification: these notes are source-of-truth for **run documentation** (timeline, decisions, blockers, user interactions), not for core workflow/policy definitions.

## Documentation granularity requirement
- Notes must include both major and small actions.
- For each meaningful action, log: what, why, when, context, touched files/tools/commands, and outcome.
- Maintain a fine-grained chronological execution log; avoid end-only summary logging.

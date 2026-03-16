---
agent: 'agent'
description: 'Execute full SentinelFetal2 migration from pip/requirements to uv with deterministic lockfile and Docker CPU-safe torch resolution.'
---

Migrate this repository to an authoritative uv workflow.

Before acting, inspect relevant migration resources:
- `.github/instructions/uv-migration-orchestrator.instructions.md`
- `.github/instructions/uv-migration.instructions.md`
- `.github/instructions/docker-uv-cpu-torch.instructions.md`
- `.github/instructions/dependency-classification.instructions.md`
- `.github/skills/uv-migration-checklist/SKILL.md`

## Required outcome
- Canonical dependency management: `pyproject.toml` + `uv.lock`.
- Legacy `requirements.txt` is no longer the source of truth.
- Docker dependency install path is uv-based and avoids accidental GPU-heavy torch installs for CPU target.
- Setup/run docs are updated to uv-first instructions.

## Repository constraints
- Backend must keep working from `api.main:app`.
- Artifact validation and model-loading flow must remain intact.
- Python version must be selected as the newest safe minor supported by runtime dependencies and deployment constraints.
- Interpreter/version management must be uv-native (`project.requires-python` + `.python-version` as applicable).
- Migration validation must run in a virtual environment.
- Migration work must run on a dedicated non-default branch.

## Work plan
1. Audit imports and install instructions.
2. Build runtime/dev/optional dependency mapping.
3. Select Python baseline by compatibility evidence (not historical assumption).
4. Apply pyproject + lockfile migration.
5. Update Docker and docs.
6. Run validation gates and summarize deltas.

## Validation gates
- Lockfile is present and current.
- Environment sync works from clean state.
- Backend import/startup path remains valid.
- No unintentional CUDA-heavy torch pull in CPU-target Docker build path.
- Dependency set is both resolvable/legal and as up-to-date as compatibility allows.
- If browser automation is available and services can start, perform visible frontend validation with screenshot evidence.

## Reporting format
- Files changed
- Stage-by-stage summary
- Fine-grained action timeline (small + major actions, with rationale)
- Dependency bucket decisions
- Commands/checks executed
- Pack components actively followed / consulted / known but unused
- Completed edits vs unverified assumptions
- Gate statuses as Passed / Blocked / Skipped (with reason)
- Issues found and mitigations
- Follow-up recommendations
- Final summary in Hebrew

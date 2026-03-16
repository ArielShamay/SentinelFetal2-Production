# SentinelFetal2 UV Migration Pack

This pack provides a complete customization bundle for running a safe, reproducible migration from legacy pip/requirements workflows to uv.

## Components

- `.github/copilot-instructions.md`
  - Minimal migration routing layer only (not broad repository governance).
- `.github/instructions/uv-migration-orchestrator.instructions.md`
  - Migration-only orchestration map, enforcement order, and reporting discipline.
- `.github/instructions/uv-migration.instructions.md`
  - End-to-end migration rules and required verification gates.
- `.github/instructions/docker-uv-cpu-torch.instructions.md`
  - Docker-specific rules with CPU-first torch safeguards.
- `.github/instructions/dependency-classification.instructions.md`
  - Runtime/dev/optional bucketing policy.
- `.github/agents/uv-migration-architect.agent.md`
  - Dedicated custom agent role for migration execution and orchestration across pack components.
- `.github/prompts/uv-migration-execution.prompt.md`
  - Reusable execution prompt template aligned with orchestration and reporting contract.
- `.github/skills/uv-migration-checklist/`
  - Skill with migration checks, reporting expectations, and references:
    - `references/acceptance-criteria.md`
    - `references/dependency-bucketing.md`
    - `references/start-state-baseline.md`
    - `references/package-names-only-resolution.md`
- `.github/migration-notes/`
  - Real-time working notes for run documentation/traceability, maintained during execution and used as primary reporting source.
  - Includes fine-grained execution logging (not only major milestones).

## Recommended execution order

1. Use the `UV Migration Architect` custom agent.
2. Do a one-time baseline read of `/.github/UV_MIGRATION_PACK.md` and core mapped resources.
3. Apply orchestration instructions first, then execution/specialized instruction files with targeted per-stage reads.
3. Invoke the `uv-migration-execution` prompt when a reusable execution scaffold is needed.
4. Use the `uv-migration-checklist` skill before finalizing.
5. Confirm all acceptance criteria pass.

## Notes source-of-truth scope
- `/.github/migration-notes/` is source-of-truth for **what happened during the run** (decisions, blockers, interactions, evidence trail).
- Core migration policy/workflow authority is defined by instructions/agent/prompt/skill pack files.

## Notes granularity expectation
- The run documentation must include both small and major actions.
- Each action entry should capture: what/why/when/context and outcome evidence.

## Agent orchestration guidance
For this migration-only pack, the Custom Agent **should** act as the orchestration entrypoint:
- It should explicitly route work to instructions/skills/prompts by task phase.
- It should not duplicate full policy text from every file; instead it should map "when to use what" clearly.
- It should remain scoped to migration workflow behavior (not global repository governance).

Authoritative layering for migration:
1. `.github/instructions/uv-migration-orchestrator.instructions.md`
2. `.github/instructions/uv-migration.instructions.md`
3. specialized instruction files (`docker-uv-cpu-torch`, `dependency-classification`)
4. custom agent/prompt/skill execution overlays

The pack is intentionally designed to run **without operational dependency on `AGENTS.md`**.

## Mandatory references for stage 1 (current-state baseline)
- `references/start-state-baseline.md`
  - Canonical checklist for the exact migration starting state to capture before edits.
  - Defines required evidence fields (inputs, runtime entrypoints, import inventory, Python/index context, and baseline health).

## Mandatory references for names-only dependency migration
- `references/package-names-only-resolution.md`
  - Canonical workflow for ignoring version pins in `requirements*.txt` and resolving legal/fresh combinations from package names only.
  - Includes uv command patterns for Python candidate probing, names-only import, universal lock resolution, and lock/sync verification.

## Non-goals

- This pack does not enable GPU torch paths by default.

## Success definition

Migration is successful when:
- `pyproject.toml` + `uv.lock` are authoritative and valid.
- Setup/run/docs are uv-first.
- Docker path is uv-native and CPU-safe for torch.
- Verification is performed in a virtual environment (not Docker-based validation flow).
- Required gates are classified with explicit blocked/skipped reasons when applicable.
- `requirements*.txt` no longer remains in supported workflow after successful verified migration.
- Runtime behavior for `api.main:app` and artifact checks is preserved.

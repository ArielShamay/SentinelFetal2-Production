---
name: uv-migration-checklist
description: 'Production-safe migration checklist for pip/requirements.txt to uv/pyproject.toml/uv.lock with branch isolation, virtual-environment-only verification, and auditable reporting (including torch CPU-vs-GPU safeguards).'
---

# UV Migration Checklist

## When to use
Use this skill when a task asks to:
- migrate from pip/requirements to uv
- adopt `pyproject.toml` / `uv.lock`
- clean dependency drift
- modernize Docker dependency installation
- fix torch index/accelerator mismatch

## Core workflow
0. Ensure migration runs on a dedicated non-default branch.
1. Capture start-state baseline using `references/start-state-baseline.md`.
2. Read and map current install/run/docs flows.
3. Build dependency buckets: runtime, dev, optional.
4. For legacy requirements input, use names-only resolution flow from `references/package-names-only-resolution.md`.
5. Encode dependencies in `pyproject.toml`.
6. Generate and verify `uv.lock`.
7. Update Docker path to uv-native sync and CPU-safe torch strategy.
8. Update docs and deprecate legacy requirements workflow.
9. Verify reproducibility and startup behavior in a virtual environment.
10. Maintain migration working notes in real time (progress, blockers, decisions, user interactions).
11. Maintain fine-grained execution log entries for both small and major actions.

## SentinelFetal2-specific checks
- `api.main:app` still starts correctly.
- `scripts/validate_artifacts.py` remains runnable in migrated environment.
- weight download script dependencies are represented.
- Docker backend path does not silently pull CUDA package trees in CPU baseline.

## Acceptance criteria
Follow `references/acceptance-criteria.md` and fail the task if any blocker remains unresolved.

## Reporting requirement
Final reporting should include:
- actively followed / consulted / known-but-unused pack resources
- per-gate status (`Passed` / `Blocked` / `Skipped (with reason)`)
- completed edits vs unverified assumptions
- fine-grained execution timeline (what/why/when/context/outcome)
- concise Hebrew summary

## Dependency bucketing guidance
Use `references/dependency-bucketing.md` before finalizing dependency tables.

## Start-state and names-only guidance
- Use `references/start-state-baseline.md` to define and capture the current migration input state before edits.
- Use `references/package-names-only-resolution.md` when requirements versions are not trusted and only package names should seed resolution.

---
description: 'Dependency bucketing and validation strategy for pyproject-based management.'
applyTo: 'pyproject.toml,uv.lock,requirements.txt,scripts/**/*.py,api/**/*.py,src/**/*.py,README.md'
---

# Dependency bucketing strategy

## Scope
This file applies to uv migration workflow work only.
Do not reuse these migration constraints as default policy for unrelated repository tasks.

## Buckets
- **Runtime** (`project.dependencies`): strictly required to run backend/service behavior.
- **Dev/Test/Lint** (`dependency-groups`): local development and CI quality tooling.
- **Optional** (`project.optional-dependencies`): feature toggles, not baseline runtime.

## SentinelFetal2-specific notes
- Keep model/runtime stack in runtime bucket (e.g., torch, numpy, scipy, sklearn, fastapi stack).
- Evaluate legacy Dash dependencies explicitly:
  - keep in runtime only if still required by current supported run path
  - otherwise move to optional group or remove with justification
- Ensure scripts that users must run in standard setup (e.g., weight download) have their direct package needs represented.

## Validation checklist
- Every imported top-level package in runtime code resolves in a clean synced environment.
- No runtime-only import depends on a dev-only group.
- Lockfile regeneration does not introduce unexpected platform-specific drift.

## Conflict handling
- If groups conflict, declare explicit conflict intent in uv config rather than silent breakage.
- Do not accept unresolved constraints that "work on one machine" only.

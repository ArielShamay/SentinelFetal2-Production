---
description: 'End-to-end migration rules from pip/requirements to uv/pyproject for SentinelFetal2.'
applyTo: '**/*.py,**/*.toml,**/Dockerfile,docker-compose.yml,requirements*.txt,README.md,docs/**/*.md,scripts/**/*.py,api/**/*.py,src/**/*.py'
---

# UV migration execution rules

## Scope guard
These rules apply only to uv migration workflow work in this repository.
Do not reuse migration-specific policy as default governance for unrelated repository tasks.

## Objective
Migrate the repository from legacy pip/requirements-based dependency management to a uv-native project model:
- Source of truth: `pyproject.toml`
- Lockfile: `uv.lock`
- Environment execution: `uv sync` and `uv run`

## Mandatory workflow
0. Verify branch isolation before edits:
  - Migration must run on a dedicated non-default branch.
  - If current branch is the default branch, stop and report blocked until branch isolation is fixed.
1. Capture the migration start-state baseline (required evidence).
2. Audit dependency usage in code and scripts.
3. Classify dependencies into:
   - runtime (`[project.dependencies]`)
   - development (`[dependency-groups]`, typically `dev`, `test`, `lint`)
   - optional feature sets (`[project.optional-dependencies]`) only when justified
4. Use `requirements*.txt` only to derive package inventory; do not treat versions there as authoritative.
5. Select the Python baseline as the newest safe legal minor version supported by runtime and deployment constraints.
6. Run names-only dependency resolution flow with uv to obtain legal + fresh combinations.
7. Create/update `uv.lock` and verify sync behavior.
8. Update Docker and documentation to uv-native commands.
9. Keep behavior parity with existing API and inference paths.

## Stage 1 baseline reference (required)
- Follow: `.github/skills/uv-migration-checklist/references/start-state-baseline.md`
- Minimum evidence to capture before dependency edits:
  - dependency input files and their role,
  - install/run/doc command map,
  - runtime entrypoints and script-critical imports,
  - Python discovery context and constraints,
  - index/source context,
  - baseline health checks.

Do not start dependency edits until baseline evidence is captured.

## Names-only resolution policy (required)
- Follow: `.github/skills/uv-migration-checklist/references/package-names-only-resolution.md`
- Treat version specifiers from `requirements*.txt` as non-authoritative migration input.
- Build dependency candidates from package names only, then resolve with uv.
- Prefer uv project locking (`uv lock`) for final authority; use `uv pip compile --universal` as a probe tool when evaluating Python compatibility candidates.
- Dockerfile Python tags are downstream artifacts and must not be treated as dependency authority.

## Virtual-environment-only migration verification
- Perform lock resolution, install/sync, smoke tests, imports, artifact checks, and runtime verification only in a virtual environment.
- Docker is allowed as a migration target artifact (Dockerfile/compose updates), but not as the environment where migration install/validation workflow is executed.
- Verification reports must state the exact virtual environment context used.

## Classification policy (SentinelFetal2)
- Runtime dependencies must include packages required by:
  - `api/` runtime service
  - `src/inference` and model loading
  - production scripts required in deployment lifecycle
- Move test/lint/doc-only tools out of runtime into dependency groups.
- Do not keep dead legacy dependencies without justification.

## Legacy file policy
- `requirements.txt` must not remain the authoritative dependency definition.
- If retained, it must be explicitly marked legacy/generated.
- Do not edit dependency versions in `requirements.txt` first; edit `pyproject.toml` first.
- Final supported state is uv-native only; after verified successful migration, remove `requirements*.txt` from supported workflow and repository.

## Python and version policy
- Manage interpreter selection with uv (including `.python-version` and/or `--python` flows where relevant).
- Keep `project.requires-python` explicit and evidence-based.
- Do not hardcode `3.11` unless compatibility evidence requires it.
- Prefer bounded ranges over unbounded wildcards when practical.
- Package metadata alone is insufficient to justify final Python/dependency decisions.
- Minimum proof for final decision:
  - successful lock,
  - successful sync in project virtual environment,
  - successful import/runtime/artifact checks.

## Freshness and legality policy
- Target the newest legal dependency set that preserves runtime behavior.
- Ensure selected versions are globally resolvable (including transitive constraints), not just locally "working".
- Prefer uv resolver defaults that maximize compatible freshness; add targeted constraints only when required by evidence.
- Any forced downgrade or pin must include rationale in migration notes.
- When deriving from names-only inputs, use explicit evidence for:
  - selected Python baseline candidate,
  - chosen `requires-python` range,
  - legal/freshness trade-offs.

## Verification gates (must pass before completion)
- Dependency resolution succeeds and lockfile is up to date.
- Environment creation/sync is deterministic.
- Backend startup import path remains valid.
- Artifact validation script remains executable in the migrated environment.
- README and Docker instructions no longer prescribe pip-first setup.
- Final state removes canonical pip workflows and requirements-based supported paths.

## Blocked-state rule
- If any required gate cannot be executed in the virtual environment, migration must not be presented as complete.
- Separate completed edits from unverified assumptions in final reporting.
- Classify each required gate as: `Passed`, `Blocked`, or `Skipped (with reason)`.

## Visual validation rule
- If technical migration gates pass and services can start, run final visual validation by opening frontend and checking visible UI (not blank page).
- Use available browser automation tooling when present.
- If browser automation is unavailable, report visual validation as `Skipped` or `Blocked` with reason; never claim it was completed.

## Anti-patterns (forbidden)
- Replacing `requirements.txt` with another ad-hoc text file as source of truth.
- Keeping undocumented split-brain dependency state (`pyproject` and independent hand-edited requirements).
- Using GPU PyTorch wheels by accident in CPU-only target workflows.
- Shipping migration without lockfile.

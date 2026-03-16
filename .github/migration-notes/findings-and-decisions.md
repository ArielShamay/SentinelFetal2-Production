# Findings and Decisions

## Codebase findings
- Baseline dependency authority is still legacy: `requirements.txt` only; `pyproject.toml` and `uv.lock` are absent.
- Current install/run docs are pip-first (`pip install -r requirements.txt`, explicit torch CPU pip index, `python -m uvicorn`).
- Backend runtime entrypoint is `api.main:app`; artifact validation script is `scripts/validate_artifacts.py`.
- Baseline health in current system env fails due to missing runtime deps (`fastapi`, `torch`) before migration.
- Top-level external imports across runtime/scripts indicate runtime set includes FastAPI stack, scientific stack, torch, and support libs.
- Platform compatibility probes showed Python 3.14/3.13 are not safe on macOS x86_64 for torch wheels in this dependency set; Python 3.12 is the newest safe legal baseline for this run.
- Artifact verification exposed compatibility drift with unconstrained `numpy`/`scikit-learn`; stabilizing to `numpy<2` and `scikit-learn==1.6.1` restored artifact compatibility.

## Options considered
1. Keep requirements versions as authoritative and map directly to `pyproject.toml`.
2. Follow names-only migration flow and let uv resolve freshest legal dependency set under explicit Python baseline.

## Decisions made
- Decision: Branch guard passed; migration can proceed on current branch.
  - Reason: Current branch is non-default and dedicated for migration.
  - Evidence: `git branch --show-current` + origin HEAD check.
  - Tradeoff: None.
  - Execution-log entries: 002

- Decision: Treat `requirements.txt` versions as untrusted migration input; use names-only resolution policy.
  - Reason: Pack policy requires names-only resolution when legacy pins are non-authoritative.
  - Evidence: `uv-migration.instructions.md` + `package-names-only-resolution.md`.
  - Tradeoff: May diverge from historical pin set; compensated by lock/sync/runtime verification gates.
  - Execution-log entries: 001, 003

- Decision: Preserve behavior parity targets explicitly (`api.main:app` and artifact validator).
  - Reason: SentinelFetal2-specific acceptance checks require both paths to stay valid post-migration.
  - Evidence: skill and execution rules, plus source reads.
  - Tradeoff: May require targeted constraints during lock resolution.
  - Execution-log entries: 005, 009, 010

- Decision: Select Python baseline `>=3.12,<3.13`.
  - Reason: 3.14/3.13 failed platform-safe torch resolution on current macOS x86_64 verification environment; 3.12 resolved and synced successfully.
  - Evidence: names-only and platform probe outcomes; successful `uv sync --locked` in 3.12 environment.
  - Tradeoff: Not using newest globally advertised minor due platform wheel legality constraints.
  - Execution-log entries: 013, 017

- Decision: Pin `torch==2.2.2`, `numpy<2`, `scikit-learn==1.6.1`.
  - Reason: Required to pass venv sync and artifact/runtime compatibility checks with existing trained assets.
  - Evidence: sync failure with torch 2.10.0, runtime warning set during artifact checks, clean pass after constraints.
  - Tradeoff: Freshness reduced for these packages to preserve runtime integrity.
  - Execution-log entries: 016, 017, 019

- Decision: Remove `requirements.txt` after successful uv lock/sync verification.
  - Reason: enforce uv-native single dependency authority and remove split workflow.
  - Evidence: `pyproject.toml` + `uv.lock` in place; technical gates passed.
  - Tradeoff: legacy pip workflow intentionally deprecated.
  - Execution-log entries: 021

## Pack resources usage
### Actively Followed
- `.github/UV_MIGRATION_PACK.md`
- `.github/instructions/uv-migration-orchestrator.instructions.md`
- `.github/instructions/uv-migration.instructions.md`
- `.github/instructions/docker-uv-cpu-torch.instructions.md`
- `.github/instructions/dependency-classification.instructions.md`
- `.github/skills/uv-migration-checklist/SKILL.md`
- `.github/skills/uv-migration-checklist/references/start-state-baseline.md`
- `.github/skills/uv-migration-checklist/references/package-names-only-resolution.md`
- `.github/skills/uv-migration-checklist/references/dependency-bucketing.md`
- `.github/skills/uv-migration-checklist/references/acceptance-criteria.md`

### Consulted
- `.github/copilot-instructions.md` (routing context)

### Known but Unused
- `.github/prompts/uv-migration-execution.prompt.md`
- `.github/agents/uv-migration-architect.agent.md` (mode already active; file not read directly in this run)

## Trace links
- Related execution-log entries for findings: 003, 004, 005, 006, 009, 010, 013, 019
- Related execution-log entries for decisions: 001, 002, 003, 005, 013, 017, 019, 021

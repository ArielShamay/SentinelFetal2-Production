# Start-state baseline (required before dependency edits)

This reference defines the exact migration starting state that must be captured before changing dependency metadata.

## Why this is mandatory
- Prevents migration decisions from being based on stale assumptions.
- Separates "what exists now" from "what we want after migration".
- Creates auditable evidence for Python and dependency decisions.

## Required baseline sections

### 1) Branch and tool context
Capture:
- Current git branch and default branch.
- uv version used during migration.
- Active virtual environment context used for checks.

### 2) Dependency input inventory
Capture all dependency-definition inputs that currently exist, for example:
- `requirements.txt`
- `requirements-dev.txt`
- other `requirements*.txt`
- `pyproject.toml` (if present)
- existing lock artifacts (`uv.lock`, `poetry.lock`, etc.)

For each input, record:
- path
- intended role (runtime/dev/legacy/generated/unknown)
- whether versions in that file are trusted or untrusted

### 3) Install/run/docs command map
Capture the actual commands currently prescribed in:
- `README.md`
- docker docs / compose
- scripts or runbooks

For each command, classify:
- install command
- run command
- test/verification command
- deprecated/legacy command

### 4) Runtime and import surface
Capture baseline runtime entrypoints and script-critical import surface:
- service entrypoint(s), especially `api.main:app`
- production scripts expected in standard setup
- top-level import inventory from runtime paths (`api/**`, runtime `src/**`, required scripts)

### 5) Python and index context
Capture:
- project Python constraints currently declared (if any)
- `.python-version` / `.python-versions` status
- currently used Python interpreter(s)
- index/source configuration currently in effect (PyPI, custom indexes, torch index usage)

Important:
- Docker base image Python tags are input signals only, not dependency authority.

### 6) Baseline health snapshot
Run a lightweight, pre-edit snapshot and record outcomes (pass/fail + short evidence):
- import/startup smoke
- artifact validation script availability
- any known blocker already present before migration

## Output location
Write baseline results into migration notes and reference them from decision logs:
- `.github/migration-notes/findings-and-decisions.md`
- `.github/migration-notes/execution-log.md`
- `.github/migration-notes/stage-status.md`

## Baseline completion rule
Dependency edits must not start until all required baseline sections above are captured.

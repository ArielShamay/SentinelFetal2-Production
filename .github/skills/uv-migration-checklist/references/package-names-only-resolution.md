# Names-only dependency resolution with uv (ignore requirements version pins)

Use this workflow when `requirements*.txt` versions are not trusted and you want legal + fresh combinations from package names only.

## Policy
- Treat `requirements*.txt` as package-name inventory only.
- Ignore version pins/specifiers from those files for final migration decisions.
- Final authority remains `pyproject.toml` + `uv.lock`.

## Stage A — Build a names-only package list

Create a normalized names-only input file (for example: `.github/migration-notes/runtime-names.txt`) from runtime-relevant requirements sources.

Rules:
- keep package names only
- remove version specifiers (`==`, `>=`, etc.)
- remove environment markers for this seed list
- ignore options/includes that are not package names
- deduplicate

Notes:
- If you have separate runtime/dev requirements files, generate separate names-only lists and map them to runtime vs dependency groups.
- This stage creates candidate inputs, not final locked versions.

### SentinelFetal2 concrete extraction example
Input:
- `requirements.txt`

Output:
- `.github/migration-notes/runtime-names.txt`

Example extraction command:

```bash
uv run python - <<'PY'
from pathlib import Path
from packaging.requirements import Requirement

src = Path('requirements.txt')
dst = Path('.github/migration-notes/runtime-names.txt')
dst.parent.mkdir(parents=True, exist_ok=True)

names = set()
for raw in src.read_text(encoding='utf-8').splitlines():
	line = raw.strip()
	if not line or line.startswith('#'):
		continue
	if line.startswith(('-r', '--requirement', '-c', '--constraint', '--index-url', '--extra-index-url', '--find-links')):
		continue
	if line.startswith('-e '):
		line = line[3:].strip()
	try:
		req = Requirement(line)
		names.add(req.name)
	except Exception:
		pass

dst.write_text('\\n'.join(sorted(names)) + '\\n', encoding='utf-8')
print(f'wrote {len(names)} package names to {dst}')
PY
```

## Stage B — Probe legal Python baseline candidates

Use uv to probe legal compatibility from names-only input before finalizing `requires-python`.

Recommended probe command pattern:
- `uv pip compile --universal --python-version <candidate-minor> <names-file> -o <probe-output>`

Example candidate set (adjust to deployment constraints):
- 3.13, 3.12, 3.11

Concrete probe example:
- `uv pip compile --universal --python-version 3.13 .github/migration-notes/runtime-names.txt -o .github/migration-notes/probe-py313.txt`
- `uv pip compile --universal --python-version 3.12 .github/migration-notes/runtime-names.txt -o .github/migration-notes/probe-py312.txt`
- `uv pip compile --universal --python-version 3.11 .github/migration-notes/runtime-names.txt -o .github/migration-notes/probe-py311.txt`

Interpretation:
- passing probe => candidate baseline remains legal
- failing probe => candidate baseline is not legal for current package-name set

Choose the newest candidate that is legal and consistent with deployment constraints.

## Stage C — Seed project dependencies from names only

After selecting Python baseline:
1. set `project.requires-python` explicitly
2. add dependencies from names-only files

Recommended add pattern:
- `uv add --raw -r <names-file>` for names-only import without inheriting legacy bounds

Then classify into runtime/dev/optional as needed:
- runtime: `[project.dependencies]`
- dev groups: `[dependency-groups]`
- optional features: `[project.optional-dependencies]`

## Stage D — Resolve freshest legal lockfile

Lock with uv project resolver (universal lockfile):
- `uv lock --upgrade`

Then verify lock freshness and environment consistency:
- `uv lock --check`
- `uv sync --locked`
- `uv run --locked python -c "import api.main"`

Targeted upgrades (if needed):
- `uv lock --upgrade-package <package>`

## Stage E — Torch/index safeguards during names-only migration

If names list includes `torch` ecosystem packages:
- configure `tool.uv.sources` + `[[tool.uv.index]]` explicitly before final lock
- set `explicit = true` on PyTorch indexes when CPU pinning is required
- avoid accidental fallback to CUDA-heavy variants in CPU baseline

## Optional advanced controls
Use only with explicit rationale/evidence:
- constraints (`--constraint`) to narrow candidates
- overrides (`--override`) as last-resort escape hatch
- environment scoping (`tool.uv.environments` / `required-environments`) when universal scope must be constrained

## Evidence to record (required)
For each migration run using this workflow, record:
- names-only input files used
- Python candidates tested and outcomes
- selected `requires-python` and why
- lock/sync verification results
- any targeted constraints/overrides and justification

Store evidence in migration notes for auditability.

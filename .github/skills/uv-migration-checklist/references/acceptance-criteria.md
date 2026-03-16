# UV migration acceptance criteria

A migration is complete only if all checks pass:

0. **Branch isolation**
   - Migration changes were made on a dedicated non-default branch.

1. **Single source of truth**
   - `pyproject.toml` declares dependencies.
   - `uv.lock` exists and is up to date.

2. **Environment reproducibility**
   - Clean environment sync succeeds in a virtual environment.
   - Runtime imports resolve without ad-hoc installs.

3. **Runtime integrity**
   - Backend startup path remains valid (`api.main:app`).
   - Model/artifact lifecycle scripts remain runnable.

4. **Docker integrity**
   - Docker build path uses uv-native dependency flow.
   - CPU-only baseline does not unintentionally resolve CUDA-heavy torch variants.

5. **Documentation integrity**
   - README and relevant docs reflect uv-first setup.
   - canonical pip-first setup is removed.

6. **Legacy handling**
   - `requirements*.txt` is not part of supported workflow; after verified successful migration it is removed.

7. **Blocked-state discipline**
   - Required gates are classified as `Passed`, `Blocked`, or `Skipped (with reason)`.
   - Any blocked required gate prevents completion claim.

8. **Visual validation**
   - If services can start and browser automation is available, frontend visible-load validation is performed with screenshot evidence.
   - If automation is unavailable, this gate is explicitly marked `Skipped`/`Blocked` with reason.

9. **Auditability**
   - Migration report documents changed files, decisions, verification steps, and open risks.
   - Run documentation includes fine-grained chronological entries for small and major actions (what/why/when/context/outcome).

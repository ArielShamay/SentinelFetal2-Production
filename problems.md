# Problems Report for Phase 7 (Scripts & Docker)

**Reviewer:** Agent 8
**Reviewed Agent:** Agent 7
**Source Documents:** `PLAN.md` v2.0 (especially §7 and §11.14), `AGENTS.md`

This document outlines the discrepancies found between the implementation of Phase 7 and the project's planning documents.

---

### 1. Critical Deviation: Incorrect Validation Scope in `validate_artifacts.py`

*   **File:** `scripts/validate_artifacts.py`
*   **Problem:** The script includes a function `validate_recordings_dir` and a command-line argument `--validate-recordings` to check the `data/recordings/` directory.
*   **Contradiction:** This directly violates the plan, which explicitly states this is a **runtime check**, not a build-time one. `PLAN.md §11.14` is unambiguous: *"data/recordings/ is NOT checked here — it is volume-mounted at runtime. Add this check in the FastAPI lifespan (startup event) instead."*
*   **Impact:** Running this validation at build time is conceptually wrong. If recordings are managed dynamically or mounted only at runtime, this check would fail the build unnecessarily if the data volume isn't present during the `docker build` process. The agent included the logic against direct orders.

### 2. Configuration Drift: Unspecified Settings in `docker-compose.yml`

*   **File:** `docker-compose.yml`
*   **Problem:** The file contains several configurations not specified in the plan.
*   **Deviations:**
    1.  **Overly Complex Healthcheck:** The plan suggested a simple `curl` command. The implementation uses a verbose inline Python script: `python -c "import urllib.request; urllib.request.urlopen(...)"`. While functional, it's not the standard, simple approach requested.
    2.  **`CORS_ORIGINS` Environment Variable:** An environment variable for `CORS_ORIGINS` is defined. The plan clearly separates development (where CORS is handled by Vite's proxy) from production (where Nginx acts as a reverse proxy, making CORS from the backend unnecessary). Including this in the production compose file indicates a misunderstanding of the deployment strategy.

### 3. Minor Deviation: Extraneous Headers in `nginx.conf`

*   **File:** `frontend/nginx.conf`
*   **Problem:** The Nginx configuration adds `Host`, `X-Real-IP`, and `X-Forwarded-For` headers to proxied requests.
*   **Contradiction:** The plan provided a minimal, exact `nginx.conf` file that did not include these headers.
*   **Impact:** This is a low-impact deviation, as these headers are common. However, it demonstrates a failure to adhere strictly to the provided specification.

### 4. Missing File: `.env.example` Not Created

*   **File:** `.env.example`
*   **Problem:** The agent did not create the `.env.example` file at the project root.
*   **Contradiction:** `AGENTS.md` for Phase 7 explicitly lists `.env.example` as a required output file. The plan (`PLAN.md §11.14`) also shows its expected content.
*   **Impact:** This missing file harms developer experience. New developers cloning the repository won't have a template for the required environment variables.

---

## Summary of Assessment

Agent 7 successfully implemented the core Docker and Nginx configurations. The build process is functional. However, the agent failed to follow the plan's specifications precisely, leading to a critical logical error in the validation script's scope and several instances of configuration drift. The failure to create the `.env.example` file is also a notable omission.

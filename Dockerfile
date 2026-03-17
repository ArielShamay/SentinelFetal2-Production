FROM python:3.12-slim AS backend
WORKDIR /app

ARG UV_VERSION=0.9.7
RUN pip install --no-cache-dir "uv==$UV_VERSION"

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

RUN mkdir -p data/recordings logs

# Copy only the backend runtime surface. Frontend/docs/dev tooling stay out of the image.
COPY api ./api
COPY src ./src
COPY generator ./generator
COPY scripts ./scripts
COPY config ./config
COPY artifacts ./artifacts
COPY weights ./weights
COPY data/god_mode_catalog.json ./data/god_mode_catalog.json
COPY data/recordings ./data/recordings

# Validate that all required artifacts are present and well-formed.
# Fails the build early if artifacts/ or weights/ are missing.
RUN uv run --frozen python scripts/validate_artifacts.py

EXPOSE 8000
CMD ["uv", "run", "--frozen", "uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]

FROM python:3.12-slim AS backend
WORKDIR /app

RUN pip install --no-cache-dir uv

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY . .

# Validate that all required artifacts are present and well-formed.
# Fails the build early if artifacts/ or weights/ are missing.
RUN uv run --frozen python scripts/validate_artifacts.py

EXPOSE 8000
CMD ["uv", "run", "--frozen", "uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]

FROM python:3.11-slim AS backend
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Validate that all required artifacts are present and well-formed.
# Fails the build early if artifacts/ or weights/ are missing.
RUN python scripts/validate_artifacts.py

EXPOSE 8000
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]

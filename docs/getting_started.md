# SentinelFetal2 Getting Started

This guide explains every supported way to start the project from a fresh checkout.

## Choose a Workflow

| Workflow | Best for | Tools you need on your machine | How many processes start | Frontend URL |
|----------|----------|--------------------------------|--------------------------|--------------|
| Local run | Direct Python and frontend development without Docker | Python `3.12`, `uv`, Node.js `18+` | 2 manual terminals | `http://localhost:5173` |
| Docker dev | Containerized development with hot reload | Docker Desktop | 2 Docker services | `http://localhost:5173` |
| Docker prod-like | Containerized deployment-style check | Docker Desktop | 2 Docker services | `http://localhost` |

The repository already includes the production artifacts, fold weights, and demo recordings needed for local inference and Docker runs. You do not need a separate model download step.

## Common First Step

Clone the repository:

```bash
git clone https://github.com/ArielShamay/SentinelFetal2-Production.git
cd SentinelFetal2-Production
```

## Workflow 1 — Run Locally

Choose this path if you want to work directly with Python and Node.js outside Docker.

### Requirements

- Python `3.12`
- `uv`
- Node.js `18+`

### Install Backend Dependencies

```bash
uv sync --locked
```

The project uses `uv` lock data and CPU-first PyTorch resolution metadata.

### Install Frontend Dependencies

```bash
cd frontend
npm install
cd ..
```

### Start the Backend

Open Terminal 1 in the repository root:

```bash
uv run --locked uvicorn api.main:app --port 8000
```

Expected startup output includes lines such as:

```text
SentinelFetal2 starting up
Loaded 5 PatchTST fold models
SegmentStore loaded: 2479 entries across 9 event types
Uvicorn running on http://0.0.0.0:8000
```

### Start the Frontend

Open Terminal 2 in the repository root:

```bash
cd frontend
npm run dev
```

Expected startup output includes:

```text
VITE v5.4.x ready
Local: http://localhost:5173/
```

### Use the UI

Open `http://localhost:5173` in your browser.

Then:

1. Choose how many beds you want to simulate.
2. Click `▶ Start`.
3. Wait for data to warm up.

Tip: click `10×` if you want a much faster warmup during demos.

### Stop the Local Workflow

- Stop the simulation in the UI with `⏹ Stop` if needed.
- Press `Ctrl+C` in the backend terminal.
- Press `Ctrl+C` in the frontend terminal.

## Workflow 2 — Run with Docker

Choose this path if you want Docker to start both services for you.

### Docker Mental Model

There are always two services:

- `backend`
- `frontend`

There are two Docker run modes:

- `dev`: backend with live reload, frontend served by Vite on port `5173`
- `prod-like`: self-contained backend image, frontend served by nginx on port `80`

There are also two ways to launch those modes:

- raw `docker compose` commands
- the repository-local `./just` wrapper

### Optional: Install the Repository-Local `just` Wrapper

If you want shorter commands, run:

```bash
./setup just
```

This does the following:

- detects `mac`, `linux`, or `windows-wsl`
- downloads `just` into `.tools/just`
- keeps your global `PATH` unchanged

After that, you can use `./just ...` from the repository root.

### Docker Dev Mode

Use this when you want Docker, but still want a development-style frontend and backend.

First run:

```bash
docker compose up --build
```

Equivalent `just` command:

```bash
./just dev-build
```

Later runs without forcing a rebuild:

```bash
docker compose up
```

```bash
./just dev
```

What you get:

- frontend at `http://localhost:5173`
- backend API at `http://localhost:8000`
- Vite dev server for the frontend
- backend running with `uvicorn --reload`

### Docker Prod-Like Mode

Use this when you want a containerized run closer to deployment behavior.

First run:

```bash
docker compose -f docker-compose.prod.yml up --build -d
```

Equivalent `just` command:

```bash
./just prod-build
```

Later runs without forcing a rebuild:

```bash
docker compose -f docker-compose.prod.yml up -d
```

```bash
./just prod
```

What you get:

- frontend at `http://localhost`
- backend API at `http://localhost:8000`
- frontend served by nginx
- backend running from the self-contained backend image

### Stop the Docker Workflows

Dev mode:

```bash
docker compose down
```

```bash
./just dev-down
```

Prod-like mode:

```bash
docker compose -f docker-compose.prod.yml down
```

```bash
./just prod-down
```

## How to Decide

Choose **local run** if:

- you want direct control over Python and Node.js processes
- you are working mostly outside Docker

Choose **Docker dev** if:

- you want containerized development
- you still want hot reload and fast UI iteration

Choose **Docker prod-like** if:

- you want a reproducible container run closer to deployment behavior
- you want to verify the self-contained backend image and nginx frontend

## Related Documentation

- Docker architecture and concepts: [docker_guide.md](/Users/tzoharlary/Documents/Projects/SentinelFetal2-Production/docs/docker_guide.md)
- High-level project architecture: [ARCHITECTURE.md](/Users/tzoharlary/Documents/Projects/SentinelFetal2-Production/docs/ARCHITECTURE.md)

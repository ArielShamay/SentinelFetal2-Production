# SentinelFetal2 — Production System

Automated fetal distress detection from CTG (Cardiotocography) signals in real time.

---

## Overview

CTG monitoring is the clinical standard for fetal surveillance during labor, but interpretation is highly subjective — inter-rater agreement is only 30–50%. SentinelFetal2 provides consistent, automated risk scoring for **metabolic acidosis** (pH < 7.15 AND BDecf ≥ 8 mmol/L) from raw CTG data (FHR + UC at 4 Hz).

### Two complementary models

| Component | Approach | Role |
|-----------|----------|------|
| **PatchTST** (AI) | Deep learning | Detects subtle temporal patterns |
| **Clinical Rules Engine** | Deterministic rules | Encodes Israeli clinical guidelines |
| **LR Meta-classifier** | Logistic regression | Combines both into a final risk score |

### Performance

| Metric | Value |
|--------|-------|
| OOF AUC (metabolic labels, 5-fold, n=552) | **0.7386** [95% CI: 0.678, 0.797] |
| REPRO_TRACK AUC (n=55) | **0.8285** [95% CI: 0.700, 0.932] |

---

## Project Structure

```
SentinelFetal2-Production/
├── api/               # FastAPI backend (WebSocket + REST)
├── src/
│   ├── model/         # PatchTST architecture
│   ├── inference/     # Sliding window pipeline
│   ├── rules/         # Clinical rules engine
│   ├── features/      # Feature extraction
│   └── god_mode/      # Manual signal injection (dev/demo)
├── frontend/          # React + TypeScript ward monitoring UI
├── artifacts/         # Trained meta-classifier (LR + scaler)
├── generator/         # CTG replay simulator
├── data/
│   ├── recordings/    # Demo .npy CTG recordings for local runs
│   └── god_mode_catalog.json
├── weights/           # PatchTST fold weights for local inference
└── docs/              # Architecture and planning docs
```

---

## Getting Started

Choose one workflow:

| Workflow | Best for | Install on your machine | Start command | Open |
|----------|----------|-------------------------|---------------|------|
| **Run locally** | Direct Python/Node development | Python `3.12`, `uv`, Node.js `18+` | `uv run ...` + `npm run dev` | `http://localhost:5173` |
| **Docker dev** | Containerized development with hot reload | Docker Desktop | `docker compose up --build` or `./just dev-build` | `http://localhost:5173` |
| **Docker prod-like** | Containerized deployment-style run | Docker Desktop | `docker compose -f docker-compose.prod.yml up --build -d` or `./just prod-build` | `http://localhost` |

For the full step-by-step guide, see [docs/getting_started.md](docs/getting_started.md). For Docker architecture and background, see [docs/docker_guide.md](docs/docker_guide.md).

The repository already includes the production artifacts, fold weights, and demo recordings required for local inference and Docker runs.

### First Step for All Workflows

Clone the repository first:

```bash
git clone https://github.com/ArielShamay/SentinelFetal2-Production.git
cd SentinelFetal2-Production
```

<details>
<summary><strong>Option A — Run Locally</strong></summary>

Use this workflow when you want direct control over the Python and frontend processes without Docker.

Requirements:

- Python `3.12`
- `uv`
- Node.js `18+`

Install backend dependencies:

```bash
uv sync --locked
```

Install frontend dependencies:

```bash
cd frontend
npm install
cd ..
```

Start the backend in Terminal 1:

```bash
uv run --locked uvicorn api.main:app --port 8000
```

Start the frontend in Terminal 2:

```bash
cd frontend
npm run dev
```

Then open **http://localhost:5173**, click **▶ Start**, and use **10×** if you want to shorten the warmup period.

Stop the local workflow with `Ctrl+C` in each terminal.

</details>

---

<details>
<summary><strong>Option B — Run with Docker</strong></summary>

Use this workflow when you want Docker to start both services for you. There are always two services, `backend` and `frontend`, and there are two Docker run modes:

- `dev`: Vite frontend on `http://localhost:5173` with hot reload
- `prod-like`: nginx frontend on `http://localhost` with a more deployment-style runtime

You can launch those Docker modes in two ways:

- raw Docker commands
- the repository-local `./just` wrapper

If you want the wrapper, run this once per checkout:

```bash
./setup just
```

This downloads a repository-local `just` binary into `.tools/just` and does not modify your global `PATH`.

### Docker dev

| How | First run | Later runs | Stop | Open |
|-----|-----------|------------|------|------|
| Raw Docker | `docker compose up --build` | `docker compose up` | `docker compose down` | `http://localhost:5173` |
| `./just` | `./just dev-build` | `./just dev` | `./just dev-down` | `http://localhost:5173` |

### Docker prod-like

| How | First run | Later runs | Stop | Open |
|-----|-----------|------------|------|------|
| Raw Docker | `docker compose -f docker-compose.prod.yml up --build -d` | `docker compose -f docker-compose.prod.yml up -d` | `docker compose -f docker-compose.prod.yml down` | `http://localhost` |
| `./just` | `./just prod-build` | `./just prod` | `./just prod-down` | `http://localhost` |

</details>

---

## Using the UI

### Viewing a bed in detail

Click any bed card — a **floating modal** opens over the ward showing the full CTG chart, risk gauge, clinical findings, and alert history. All other bed cards continue updating in the background. Close with **×** or by clicking outside the panel.

---

## God Mode (Demo / Teaching Tool)

God Mode lets you inject pathological CTG events manually into any bed — useful for demonstrating the system's response to known patterns.

1. Click any bed card to open its detail modal
2. In the **God Mode** panel, enter the PIN: `1234`
3. Select an event type (e.g. "Late Decels"), set severity and duration
4. Click **"Inject Event"**

The system swaps the bed's recording to a real pathological recording from the catalog and applies feature overrides, causing the risk score to respond immediately. Events marked with a star (★) have real recordings available for signal swap.

---

## API Reference

The backend exposes a REST + WebSocket API at `http://localhost:8000`.

<details>
<summary><strong>Endpoints</strong></summary>

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/health` | GET | Health check |
| `/api/beds` | GET | Current state of all beds |
| `/api/simulation/start` | POST | Start simulation |
| `/api/simulation/speed` | POST | Set replay speed — body: `{"speed": 10.0}` |
| `/api/simulation/status` | GET | Simulation running/speed/beds |
| `/api/god-mode/status` | GET | God Mode status + available event types |
| `/api/god-mode/inject` | POST | Inject an event into a bed |
| `/api/god-mode/events` | GET | Event history for a bed |
| `/api/god-mode/events/{id}` | DELETE | End a specific active event |
| `/api/god-mode/clear/{bed_id}` | DELETE | Clear all events from a bed |
| `/ws/stream` | WebSocket | Real-time bed state stream |

</details>

Interactive API docs: **http://localhost:8000/docs**

---

## Data

The repository already includes the production artifacts, fold weights, and demo `.npy` recordings required for local runs.

The full original CTU-UHB dataset and sensitive clinical labels are **not included** in this repository.

---

## Tech Stack

- **Backend:** Python, FastAPI, WebSockets
- **Model:** PyTorch (PatchTST), scikit-learn (LR meta-classifier)
- **Frontend:** React, TypeScript, Vite, Tailwind CSS, lightweight-charts
- **Model assets:** repository-tracked `artifacts/` and `weights/`

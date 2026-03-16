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
│   ├── recordings/    # .npy CTG recordings (not in repo)
│   └── god_mode_catalog.json
├── weights/           # PatchTST fold weights (not in repo)
└── docs/              # Architecture and planning docs
```

---

## Prerequisites

- Python 3.12
- uv (https://docs.astral.sh/uv/)
- Node.js 18+
- A HuggingFace account with access to the private weights repo

---

## Setup (first time only)

### 1. Clone the repository

```bash
git clone https://github.com/ArielShamay/SentinelFetal2-Production.git
cd SentinelFetal2-Production
```

### 2. Install Python dependencies (uv-native)

```bash
uv sync --locked
```

> The project is configured for **CPU-first PyTorch resolution** via uv sources/index metadata.

### 3. Download model weights

Weights are stored on Hugging Face (private repo). You need a HuggingFace account with access.

```bash
huggingface-cli login   # enter your HF token when prompted
uv run --locked python scripts/download_weights.py
```

This downloads 5 cross-validation fold weights into `weights/`:
```
weights/fold0_best_finetune.pt
weights/fold1_best_finetune.pt
weights/fold2_best_finetune.pt
weights/fold3_best_finetune.pt
weights/fold4_best_finetune.pt
```

### 4. Install frontend dependencies

```bash
cd frontend
npm install
cd ..
```

---

## Running the System

Open **two terminals** from the project root.

### Terminal 1 — Backend

```bash
uv run --locked uvicorn api.main:app --port 8000
```

Wait for:
```
SentinelFetal2 starting up
Loaded 5 PatchTST fold models
SegmentStore loaded: 2479 entries across 9 event types
Uvicorn running on http://0.0.0.0:8000
```

### Terminal 2 — Frontend

```bash
cd frontend
npm run dev
```

Wait for:
```
VITE v5.4.x  ready in ~800ms
Local:   http://localhost:5173/
```

### Start the simulation

1. Open **http://localhost:5173** in your browser.
2. In the top bar, set the **Beds** counter (1–16) to the number of beds you want.
3. Click **▶ Start** — the system assigns random CTG recordings to each bed and begins streaming.
4. After ~450 seconds (7.5 min) of warmup per bed, risk scores begin appearing.

> **Tip:** Click **10×** to compress warmup to ~45 seconds.

### Stopping the System

**Stop the simulation** (keeps servers running, resets all beds):
- Click **⏹ Stop** in the top bar.

**Shut down the backend**:
- Press `Ctrl+C` in Terminal 1 (uv run + uvicorn).

**Shut down the frontend**:
- Press `Ctrl+C` in Terminal 2 (Vite).

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

Interactive API docs: **http://localhost:8000/docs**

---

## Data

Patient data (CTG recordings and clinical labels) is **not included** in this repository for privacy reasons. The system was trained on the CTU-UHB Intrapartum CTG Database.

---

## Tech Stack

- **Backend:** Python, FastAPI, WebSockets
- **Model:** PyTorch (PatchTST), scikit-learn (LR meta-classifier)
- **Frontend:** React, TypeScript, Vite, Tailwind CSS, lightweight-charts
- **Model storage:** Hugging Face Hub

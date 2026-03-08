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

- Python 3.11+
- Node.js 18+
- A HuggingFace account with access to the private weights repo

---

## Setup (first time only)

### 1. Clone the repository

```bash
git clone https://github.com/ArielShamay/SentinelFetal2-Production.git
cd SentinelFetal2-Production
```

### 2. Install Python dependencies

```bash
python -m pip install fastapi uvicorn[standard] pydantic numpy scipy scikit-learn
python -m pip install torch --index-url https://download.pytorch.org/whl/cpu
```

> For GPU support, replace the torch install URL with the appropriate CUDA version from https://pytorch.org/get-started/locally/

### 3. Download model weights

Weights are stored on Hugging Face (private repo). You need a HuggingFace account with access.

```bash
huggingface-cli login   # enter your HF token when prompted
python scripts/download_weights.py
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
python -m uvicorn api.main:app --port 8000
```

Expected output:
```
SentinelFetal2 starting up
Loaded 5 PatchTST fold models
SegmentStore loaded: 2479 entries across 9 event types
SentinelFetal2 startup complete. beds=4
Uvicorn running on http://0.0.0.0:8000
```

### Terminal 2 — Frontend

```bash
cd frontend
npm run dev
```

Expected output:
```
VITE v5.4.x  ready in ~800ms
Local:   http://localhost:5173/
```

### Start the simulation

Once both servers are running, open your browser at **http://localhost:5173**.

Click **"Start Simulation"** in the top bar. The system will:
1. Assign random CTG recordings to 4 beds
2. Begin streaming at real-time speed (1x)
3. After ~450 seconds of warmup, risk scores start appearing

> **Tip:** Click the speed control and set it to **10x** to skip warmup in ~45 seconds.

---

## God Mode (Demo / Teaching Tool)

God Mode lets you inject pathological CTG events manually into any bed — useful for demonstrating the system's response to known patterns.

1. Navigate to any bed's detail view (click a bed card)
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

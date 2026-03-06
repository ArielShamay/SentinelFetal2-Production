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
├── scripts/           # Utility scripts
├── config/            # Training configuration
├── generator/         # CTG replay simulator
└── docs/              # Architecture and planning docs
```

---

## Setup

### 1. Clone the repository

```bash
git clone https://github.com/ArielShamay/SentinelFetal2-Production.git
cd SentinelFetal2-Production
```

### 2. Install Python dependencies

```bash
pip install -r requirements.txt
```

### 3. Download model weights

Weights are stored on Hugging Face (private repo). You need a HuggingFace account with access.

```bash
huggingface-cli login   # enter your HF token when prompted
python scripts/download_weights.py
```

This will download the 5 cross-validation fold weights into `weights/`.

### 4. Install frontend dependencies

```bash
cd frontend
npm install
```

---

## Running

### Backend (FastAPI)

```bash
uvicorn api.main:app --reload --port 8000
```

### Frontend (React)

```bash
cd frontend
npm run dev
```

### CTG Simulator (replay recorded signals)

```bash
python generator/replay.py
```

---

## Data

Patient data (CTG recordings and clinical labels) is **not included** in this repository for privacy reasons. The system was trained on the CTU-UHB Intrapartum CTG Database.

---

## Tech Stack

- **Backend:** Python, FastAPI, WebSockets
- **Model:** PyTorch (PatchTST), scikit-learn (LR meta-classifier)
- **Frontend:** React, TypeScript, Vite, Tailwind CSS
- **Model storage:** Hugging Face Hub

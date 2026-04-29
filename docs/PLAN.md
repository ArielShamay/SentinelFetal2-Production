# SentinelFetal2 — תכנית פיתוח מלאה

**גרסה:** 2.0 | **תאריך:** 2026-03-05  
**מחבר:** Ariel Shamay  
**מצב:** תכנון — מוכן לביצוע

---

## תוכן עניינים

1. [סקירת ארכיטקטורה](#1-סקירת-ארכיטקטורה)
2. [שלב 1 — Pipeline Core (`src/inference/pipeline.py`)](#2-שלב-1--pipeline-core)
3. [שלב 2 — Generator: Replay Engine](#3-שלב-2--generator-replay-engine)
4. [שלב 3 — Backend: FastAPI](#4-שלב-3--backend-fastapi)
5. [שלב 4 — Frontend: React + lightweight-charts](#5-שלב-4--frontend-react--lightweight-charts)
6. [שלב 5 — אינטגרציה וטסטים](#6-שלב-5--אינטגרציה-וטסטים)
7. [מבנה קבצים סופי](#7-מבנה-קבצים-סופי)
8. [עקרונות עיצוב](#8-עקרונות-עיצוב)
9. [ביצועים: 16 לידות במקביל](#9-ביצועים-16-לידות-במקביל)
10. [God Mode — שליטה ידנית והזרקת אירועים](#10-god-mode--שליטה-ידנית-והזרקת-אירועים)
11. [ניתוח פערים, תיקונים ושיפורים לייצור](#11-ניתוח-פערים-תיקונים-ושיפורים-לייצור)

---

## 1. סקירת ארכיטקטורה

### תמונת המערכת

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          SentinelFetal2                                  │
│                                                                         │
│  .npy recordings (data/recordings/)                                     │
│  ⚠ ALREADY PREPROCESSED: FHR∈[0,1] = (bpm-50)/160, UC∈[0,1] = mmHg/100│
│       │                                                                 │
│       ▼ generator/replay.py                                             │
│  ReplayEngine (up to 16 beds)                                           │
│  ├── bed_1: recording 1001.npy → 4Hz normalized stream                  │
│  ├── bed_2: recording 1023.npy → 4Hz normalized stream                  │
│  └── ... up to bed_16                                                   │
│       │                                                                 │
│       ▼ every 24 samples (6 sec) = one new PatchTST window score        │
│  src/inference/pipeline.py                                              │
│  ├── SentinelRealtime (per bed)                                         │
│  │   ├── RingBuffer: 7200 normalized samples (FHR+UC) = 30 min @ 4Hz   │
│  │   ├── PatchTST × 5 folds on ring[-1800:] → P(acidemia) window score │
│  │   ├── extract_recording_features(window_scores) → 12 AI features    │
│  │   ├── extract_clinical_features(normalized_signal) → 11 features    │
│  │   ├── + 2 global features (overall mean/std prob)                   │
│  │   ├── StandardScaler + LogisticRegression → risk_score [0,1]        │
│  │   └── alert = risk_score > 0.4605 (from production_config.json)     │
│  │                                                                      │
│       ▼ FastAPI (api/)                                                  │
│  ┌──────────────────────────────────────────────────────────────┐       │
│  │  PipelineManager (singleton)                                  │       │
│  │  ├── orchestrates ReplayEngine + 16 × SentinelRealtime        │       │
│  │  ├── AsyncBroadcaster → WebSocket → frontend                  │       │
│  │  └── REST: /api/beds, /api/simulation, /api/health            │       │
│  └──────────────────────────────────────────────────────────────┘       │
│       │ WebSocket ws://localhost:8000/ws/stream                         │
│       ▼ JSON batch_update every 6 sec (all active beds combined)        │
│  frontend/ (React + Vite + lightweight-charts)                          │
│  ├── WardView: grid 1–16 cards, sorted by risk_score desc               │
│  │   └── BedCard: sparkline + FHR/UC values (denormalized) + risk gauge │
│  └── DetailView: full CTG trace + risk timeline + clinical findings     │
└─────────────────────────────────────────────────────────────────────────┘
```

> **⚠ נקודה קריטית:** קבצי `.npy` נוצרו ע"י `src/data/preprocessing.py:process_and_save_recording()` ונשמרו **כבר מנורמלים** (`shape=(2,T)`, FHR∈[0,1], UC∈[0,1]). ה-`ReplayEngine` מזרים ערכים מנורמלים. ה-`SentinelRealtime` מקבל ערכים מנורמלים ולא מבצע נורמליזציה נוספת. **להצגה ב-UI** בלבד יש לדנורמל: `bpm = val * 160 + 50`, `mmHg = val * 100`.

### הבדלים מ-SentinelFetal המקורי

| תכונה | SentinelFetal (orig) | SentinelFetal2 Production |
|-------|---------------------|--------------------------|
| מקור נתונים | **מחולל סינתטי** (generators/) | **Replay קבצי .npy אמיתיים** |
| מודל AI | MiniRocket + XGBoost | **PatchTST + LR Meta-classifier** |
| עיצוב | כחול/צהוב/אדום קטגוריות | **שחור-לבן בלבד** |
| God Mode | זמין | **זמין (סקשן 10)** |
| מספר חולים | 4–20 | **1–16 (לידות)** |

### טכנולוגיות

| שכבה | טכנולוגיה | הסיבה |
|------|-----------|-------|
| Backend | **FastAPI + asyncio** | async-native, WebSocket מובנה |
| Frontend | **React + Vite + TypeScript** | SPA מהיר, ecosystem עשיר |
| גרפים | **TradingView lightweight-charts** | WebGL, 60fps, API נקי |
| State | **Zustand** | קל, no boilerplate |
| תקשורת real-time | **WebSocket (JSON)** | push-based, no polling |
| CSS | **Tailwind CSS** | utility-first, קל להגיע ל-B&W |

---

## 2. שלב 1 — Pipeline Core

**קובץ:** `src/inference/pipeline.py`  
**תלויות:** כל הקוד הקיים ב-`src/`

### מטרה

מחלקה `SentinelRealtime` — ה-glue layer שמחבר:
- `src/data/preprocessing.py` → נורמליזציה
- `src/inference/sliding_window.py` → PatchTST inference
- `src/inference/alert_extractor.py` → 12 פיצ'רי AI
- `src/features/clinical_extractor.py` → 11 פיצ'רים קליניים
- `artifacts/production_scaler.pkl` + `production_lr.pkl` → risk_score

### ממשק מלא

```python
# src/inference/pipeline.py

@dataclass
class BedState:
    """State snapshot for one bed, emitted every 6 seconds.

    Field names MUST match production_config.json feature_names exactly
    for clinical fields — they are used to assemble the LR feature vector.
    """
    # ── Identity ──────────────────────────────────────────────────────────
    bed_id: str                              # e.g. "bed_01"
    recording_id: str                        # e.g. "1023"
    timestamp: float                         # unix time

    # ── AI Model Output ───────────────────────────────────────────────────
    risk_score: float                        # LR output [0, 1]
    alert: bool                              # risk_score > decision_threshold (0.4605)
    window_prob: float                       # latest PatchTST window P(acidemia)

    # ── Display (denormalized for UI) ─────────────────────────────────────
    fhr_latest: list[float]                  # last 24 FHR values in BPM (denorm: val*160+50) — matches stride!
    uc_latest: list[float]                   # last 24 UC values in mmHg (denorm: val*100)

    # ── Clinical Features (from clinical_extractor — exact names) ─────────
    baseline_bpm: float                      # CLINICAL_FEATURE_NAMES[0]
    is_tachycardia: float                    # CLINICAL_FEATURE_NAMES[1] (0 or 1)
    is_bradycardia: float                    # CLINICAL_FEATURE_NAMES[2] (0 or 1)
    variability_amplitude_bpm: float         # CLINICAL_FEATURE_NAMES[3]
    variability_category: float              # CLINICAL_FEATURE_NAMES[4]: 0=absent,1=minimal,2=moderate,3=marked
    n_late_decelerations: int                # CLINICAL_FEATURE_NAMES[5]
    n_variable_decelerations: int            # CLINICAL_FEATURE_NAMES[6]
    n_prolonged_decelerations: int           # CLINICAL_FEATURE_NAMES[7]
    max_deceleration_depth_bpm: float        # CLINICAL_FEATURE_NAMES[8]
    sinusoidal_detected: bool                # CLINICAL_FEATURE_NAMES[9]
    tachysystole_detected: bool              # CLINICAL_FEATURE_NAMES[10]

    # ── Playback ──────────────────────────────────────────────────────────
    elapsed_seconds: float                   # recording playback position
    warmup: bool                             # True during first 7.5 min (< 1800 samples buffered)


class SentinelRealtime:
    """
    Single-bed real-time inference pipeline.

    Receives NORMALIZED FHR/UC samples at 4 Hz.
    (FHR: [0,1] = (bpm-50)/160  |  UC: [0,1] = mmHg/100 — as stored in .npy files)
    Emits BedState every 24 samples (6 sec) once ring buffer has >= 1800 samples.

    Usage:
        pipeline = SentinelRealtime(bed_id="bed_01", recording_id="1023",
                                    models=loaded_models, scaler=sc, lr=lr,
                                    config=prod_cfg)
        for fhr_norm, uc_norm in stream_4hz():    # values in [0,1]
            state = pipeline.on_new_sample(fhr_norm, uc_norm)
            if state:
                broadcast(state)   # BedState contains denormalized display values
    """

    def __init__(
        self,
        bed_id: str,
        recording_id: str,
        models: list,           # 5 loaded PatchTST models (eval mode, ClassificationHead attached)
        scaler,                 # production_scaler.pkl (StandardScaler, 25 features)
        lr_model,               # production_lr.pkl (LogisticRegression)
        config: dict,           # production_config.json
    ): ...

    def on_new_sample(
        self, fhr_norm: float, uc_norm: float
    ) -> BedState | None:
        """
        Call at 4 Hz (every 0.25 sec).
        Args:
            fhr_norm: FHR normalized [0, 1]  i.e. (bpm-50)/160
            uc_norm:  UC normalized  [0, 1]  i.e. mmHg/100
        Returns:
            BedState every 24 calls (6 sec) once warmup complete (>= 1800 samples), else None.
        """
        ...

    def reset(self) -> None:
        """Clear ring buffers and window_scores — called when recording loops."""
        ...
```

### פרטי מימוש

#### Ring Buffers
```python
from collections import deque

# Stores NORMALIZED values exactly as received from .npy / ReplayEngine
# FHR: [0, 1] = (bpm - 50) / 160  |  UC: [0, 1] = mmHg / 100
self._fhr_ring = deque(maxlen=7200)   # 30 min × 4 Hz = 7200 normalized FHR samples
self._uc_ring  = deque(maxlen=7200)   # 30 min × 4 Hz = 7200 normalized UC samples
self._sample_count = 0
self._window_scores: list[tuple[int, float]] = []  # [(start_sample, prob)] accumulates over time
```

> **⚠ Normalization invariant:** ring buffers contain normalized values throughout. PatchTST expects normalized input and `extract_clinical_features()` expects normalized input — both work directly on ring buffer slices. Only for UI display do we denormalize.

#### Logic ב-`on_new_sample`
```
כל קריאה (4Hz):
  push (fhr_norm, uc_norm) לring buffers
  sample_count += 1

כל 24 קריאות (6 שניות):
  if len(ring) >= 1800:  ← חלון ראשון זמין בדיוק אחרי 1800 samples (7.5 דקות)
    # חותכים את ה-ring הנורמלי ישירות — אין צורך לנרמל
    fhr_win = np.array(self._fhr_ring)[-1800:]         # shape (1800,) normalized
    uc_win  = np.array(self._uc_ring)[-1800:]          # shape (1800,) normalized
    signal  = np.stack([fhr_win, uc_win])              # shape (2, 1800) — ready for PatchTST

    prob = _run_ensemble(signal)                       # P(acidemia) from 5-fold ensemble
    start = self._sample_count - 1800                 # window start index in recording
    window_scores.append((start, prob))

    # LR רץ כל 6 שניות — O(25) dot product, זניח ב-CPU
    state = _compute_full_state()
    return state

  return None  # במהלך warmup (< 1800 samples)
```

> **תדירות LR:** LR מחושב **כל 6 שניות** (לא כל 60). זה מתוכנן — ה-features מצטברים לאורך הזמן (כל window_score חדש משפיע עליהם), ו-inference עצמו זול.

#### `_run_ensemble` — הפעלת 5 folds
```python
def _run_ensemble(self, signal: np.ndarray) -> float:
    """
    Args:
        signal: np.ndarray shape (2, 1800) — ALREADY NORMALIZED (FHR∈[0,1], UC∈[0,1])
                Direct slice from ring buffer — NO re-normalization needed.
    Returns:
        float: mean P(acidemia) across 5 folds, in [0, 1].
    """
    # PatchTST expects (batch=1, channels=2, seq_len=1800)
    x = torch.tensor(signal, dtype=torch.float32).unsqueeze(0)  # (1, 2, 1800)

    with torch.no_grad():
        # Each model returns logits (1, 2) — class 0=normal, class 1=acidemia
        probs = [
            torch.softmax(m(x), dim=-1)[0, 1].item()
            for m in self._models   # 5 fold models
        ]
    return float(np.mean(probs))
```

> **Thread safety:** `self._models` are read-only (eval mode). Multiple beds can call `_run_ensemble` concurrently — safe. `PipelineManager` uses `ThreadPoolExecutor(max_workers=4)` to limit CPU saturation across 16 beds.

#### `_compute_full_state` — 25 פיצ'רים + LR
```python
def _compute_full_state(self) -> BedState:
    from src.inference.alert_extractor import extract_recording_features
    from src.features.clinical_extractor import (
        extract_clinical_features, CLINICAL_FEATURE_NAMES
    )

    # ── 12 PatchTST / AI features ─────────────────────────────────────────
    # production_config["best_at"] = 0.5 — the alert threshold the LR was trained with
    at = self._config["best_at"]          # 0.5
    pt_feats = extract_recording_features(
        self._window_scores, threshold=at, inference_stride=24, n_features=12
    )  # returns dict with 12 keys in production_config feature_names order

    # ── 11 clinical features ──────────────────────────────────────────────
    # extract_clinical_features expects a normalized (2, T) signal — ring buffer is already normalized
    fhr_arr = np.array(self._fhr_ring)    # shape (T,) normalized [0,1]
    uc_arr  = np.array(self._uc_ring)     # shape (T,) normalized [0,1]
    full_signal = np.stack([fhr_arr, uc_arr])          # (2, T) normalized — no conversion needed
    clin_list   = extract_clinical_features(full_signal)  # List[float], len=11, order=CLINICAL_FEATURE_NAMES
    clin_dict   = dict(zip(CLINICAL_FEATURE_NAMES, clin_list))

    # ── 2 global features ─────────────────────────────────────────────────
    all_probs   = [p for _, p in self._window_scores]
    global_feat = [float(np.mean(all_probs)), float(np.std(all_probs))]

    # ── Assemble 25-feature vector in production_config order ─────────────
    # Order: 12 PT feats → 11 clinical → 2 global (matches production_config.json feature_names)
    x = np.array(
        list(pt_feats.values()) + clin_list + global_feat,
        dtype=np.float64,
    ).reshape(1, -1)     # (1, 25)

    # ── LR prediction ─────────────────────────────────────────────────────
    x_scaled = self._scaler.transform(x)    # StandardScaler
    risk = float(self._lr.predict_proba(x_scaled)[0, 1])

    # ── Display values — denormalize for UI ───────────────────────────────
    # Must send exactly STRIDE=24 samples per tick so frontend has no gaps.
    # Sending [-16:] would silently discard 8 samples every 6 seconds → broken CTG graph.
    fhr_display = [round(v * 160.0 + 50.0, 1) for v in list(fhr_arr)[-24:]]  # bpm — last 24 = 1 stride
    uc_display  = [round(v * 100.0, 1)         for v in list(uc_arr)[-24:]]   # mmHg

    return BedState(
        bed_id=self._bed_id,
        recording_id=self._recording_id,
        timestamp=time.time(),
        risk_score=risk,
        alert=risk > self._config["decision_threshold"],   # 0.4605492604713227
        window_prob=all_probs[-1] if all_probs else 0.0,
        fhr_latest=fhr_display,
        uc_latest=uc_display,
        # Clinical fields — exact names from CLINICAL_FEATURE_NAMES:
        baseline_bpm=clin_dict["baseline_bpm"],
        is_tachycardia=clin_dict["is_tachycardia"],
        is_bradycardia=clin_dict["is_bradycardia"],
        variability_amplitude_bpm=clin_dict["variability_amplitude_bpm"],
        variability_category=clin_dict["variability_category"],
        n_late_decelerations=int(clin_dict["n_late_decelerations"]),
        n_variable_decelerations=int(clin_dict["n_variable_decelerations"]),
        n_prolonged_decelerations=int(clin_dict["n_prolonged_decelerations"]),
        max_deceleration_depth_bpm=clin_dict["max_deceleration_depth_bpm"],
        sinusoidal_detected=bool(clin_dict["sinusoidal_detected"]),
        tachysystole_detected=bool(clin_dict["tachysystole_detected"]),
        elapsed_seconds=self._sample_count / 4.0,
        warmup=len(self._fhr_ring) < 1800,
    )
```

### טסטים

```
tests/test_pipeline.py
- test_warmup_period: על 1799 samples ראשונים — on_new_sample() מחזיר None
- test_first_output_at_1800: sample ה-1800 (הראשון שלפחות 1800 buffered) → BedState עם warmup=False
- test_risk_score_range: risk_score ∈ [0, 1] תמיד
- test_reset_clears_state: reset() → sample_count=0, window_scores=[], returns None עד 1800
- test_field_names_match_config: BedState fields תואמים CLINICAL_FEATURE_NAMES בסדר ובשם
- test_normalized_input: on_new_sample מקבל ערכים בטווח [0,1] (לא bpm)
- test_display_values_denormalized: fhr_latest ∈ [50, 210], uc_latest ∈ [0, 100]
```

---

## 3. שלב 2 — Generator: Replay Engine

**קובץ:** `generator/replay.py`

### מטרה

טעינת קבצי `.npy` מ-`data/recordings/` והזרמתם ב-4 Hz לדמות מכשיר CTG חי.  
עד 16 הקלטות רצות בו-זמנית (לידה = מיטה).

### ממשק

```python
# generator/replay.py

class RecordingReplay:
    """
    Streams a single .npy recording at 4 Hz.
    Loops infinitely when the recording ends.
    """

    def __init__(self, recording_id: str, recordings_dir: Path): ...

    def get_next_sample(self) -> tuple[float, float]:
        """
        Returns (fhr_normalized, uc_normalized) — values in [0, 1].
        ⚠ NOT bpm/mmHg — the .npy files are pre-normalized at preprocessing time.
        Caller (SentinelRealtime.on_new_sample) expects normalized input directly.
        For display: bpm = fhr_norm * 160 + 50, mmHg = uc_norm * 100.
        """
        ...

    @property
    def position_seconds(self) -> float:
        """Current playback position in seconds."""
        ...

    @property
    def recording_id(self) -> str: ...


class ReplayEngine:
    """
    Manages up to 16 beds, each replaying a recording.
    Provides a tick() method called at 4 Hz.
    """

    def __init__(
        self,
        recordings_dir: Path,
        on_sample_callback: Callable[[str, float, float], None],  # (bed_id, fhr, uc)
    ): ...

    def add_bed(self, bed_id: str, recording_id: str) -> None:
        """Register a bed. Max 16."""
        ...

    def remove_bed(self, bed_id: str) -> None: ...

    async def run(self) -> None:
        """Async loop: ticks at 4 Hz (every 0.25 sec), calls on_sample_callback."""
        ...

    def set_beds(self, bed_configs: list[dict]) -> None:
        """
        Atomic replacement of all beds.
        bed_configs = [{"bed_id": "bed_01", "recording_id": "1023"}, ...]
        """
        ...
```

### פרטי מימוש

#### טעינת קובץ `.npy`
```python
def _load_recording(self, recording_id: str) -> tuple[np.ndarray, np.ndarray]:
    path = self._dir / f"{recording_id}.npy"
    data = np.load(path)          # shape: (2, T)
    # ⚠ DATA IS ALREADY PREPROCESSED:
    # Channel 0 (FHR): normalized [0,1] = (bpm-50)/160
    # Channel 1 (UC):  normalized [0,1] = mmHg/100
    # Produced by src/data/preprocessing.py:process_and_save_recording()
    fhr_norm = data[0].astype(np.float32)   # [0,1] FHR
    uc_norm  = data[1].astype(np.float32)   # [0,1] UC
    # Handle any residual NaN (e.g. edge artifacts not caught by preprocess)
    fhr_norm = np.nan_to_num(fhr_norm, nan=0.5)   # 0.5 = 130 bpm normalized
    uc_norm  = np.nan_to_num(uc_norm,  nan=0.0)
    return fhr_norm, uc_norm
```

> **בשים לב:** `get_next_sample()` מחזיר `(fhr_normalized, uc_normalized)` בטווח [0,1]. `SentinelRealtime.on_new_sample()` מקבל ערכים מנורמלים ולא מנרמל. **גידול ל-UI בלבד:** `bpm = norm * 160 + 50`, `mmHg = norm * 100`.

#### Async tick loop
```python
async def run(self) -> None:
    TICK_INTERVAL = 0.25  # 4 Hz

    while self._running:
        t_start = asyncio.get_event_loop().time()

        for bed_id, replay in list(self._beds.items()):  # snapshot: prevent RuntimeError if set_beds() runs concurrently
            fhr, uc = replay.get_next_sample()
            # self._callback = PipelineManager.on_sample — NON-BLOCKING by design.
            # It submits work to ThreadPoolExecutor and returns immediately.
            # ⚠ Never call pipeline.on_new_sample() directly from this loop —
            # PatchTST inference (~50ms) would freeze the WebSocket event loop.
            self._callback(bed_id, fhr, uc)

        elapsed = asyncio.get_event_loop().time() - t_start
        sleep_time = max(0.0, TICK_INTERVAL - elapsed)
        await asyncio.sleep(sleep_time)
```

#### אוטומטיקה
- כשמוסיפים לידה: מוקצית הקלטה רנדומלית מ-`data/recordings/` (אם לא צויין)
- כשהקלטה מסתיימת: loop מתחיל מחדש (`position = 0`), `SentinelRealtime.reset()` נקרא
- **מניעת כפילויות:** כל הקלטה רצה לכל היותר פעם אחת במקביל

---

## 4. שלב 3 — Backend: FastAPI

### מבנה תיקיות

```
api/
├── __init__.py
├── main.py                  ← FastAPI app + lifespan
├── config.py                ← settings (env vars)
├── dependencies.py          ← Depends() helpers
├── models/
│   ├── __init__.py
│   └── schemas.py           ← Pydantic models
├── routers/
│   ├── __init__.py
│   ├── simulation.py        ← /api/simulation/*
│   ├── beds.py              ← /api/beds/*
│   └── websocket.py         ← /ws/stream
└── services/
    ├── __init__.py
    ├── pipeline_manager.py  ← singleton: manages 16 SentinelRealtime
    ├── broadcaster.py       ← async WebSocket broadcast
    └── model_loader.py      ← טוען 5 PatchTST weights + scaler/lr
```

### `api/main.py`

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    # 1. טעינת מודלים (חד-פעמי, blocking — לפני כל השאר)
    models, scaler, lr_model, config = load_production_models()

    # 2. אתחול broadcaster ראשון — PipelineManager זקוק לו
    broadcaster = AsyncBroadcaster()
    await broadcaster.start()

    # 3. אתחול PipelineManager עם broadcaster
    #    ⚠ סדר קריטי: broadcaster חייב להיות מוכן לפני שpipelines מתחילים לקבל samples
    mgr = PipelineManager(models, scaler, lr_model, config, broadcaster=broadcaster)

    # 4. אתחול ReplayEngine
    engine = ReplayEngine(
        recordings_dir=Path("data/recordings"),
        on_sample_callback=mgr.on_sample,
    )

    # ⚠ Runtime data check — volume is mounted by docker-compose, not available at build time.
    # Fail fast here rather than running silently with zero recordings.
    _recordings_dir = Path("data/recordings")
    if not _recordings_dir.exists() or not any(_recordings_dir.glob("*.npy")):
        raise RuntimeError(
            "No .npy files found in data/recordings/ — is the data volume mounted?"
        )

    # 5. הפעל replay loop כ-background task
    asyncio.create_task(engine.run())

    # 6. התחל עם 4 לידות default
    mgr.set_beds([
        {"bed_id": f"bed_{i+1:02d}", "recording_id": None}  # random
        for i in range(4)
    ], engine)

    app.state.manager     = mgr
    app.state.engine      = engine
    app.state.broadcaster = broadcaster

    yield

    await broadcaster.stop()
    engine.stop()
```

### `api/services/pipeline_manager.py`

```python
class PipelineManager:
    """
    Manages up to 16 SentinelRealtime instances.
    Thread-safe: on_sample() called from ReplayEngine's async loop.
    Routes each (bed_id, fhr_norm, uc_norm) to the correct SentinelRealtime.
    When pipeline emits BedState → push to broadcaster.
    """

    MAX_BEDS = 16

    def __init__(self, models, scaler, lr_model, config, broadcaster: AsyncBroadcaster):
        # ⚠ broadcaster is required — must be started before first on_sample() call
        self._broadcaster = broadcaster
        self._pipelines: dict[str, SentinelRealtime] = {}
        self._lock = threading.Lock()
        self._executor = ThreadPoolExecutor(max_workers=4)
        # Note: _loop is NOT stored here. push() is synchronous (queue.put_nowait),
        # so no asyncio bridge is needed from the thread pool.
        self._models = models
        self._scaler = scaler
        self._lr_model = lr_model
        self._config = config

    @property
    def god_mode_enabled(self) -> bool:
        """God Mode is system-wide — all beds created after enable() use GodModeInjector."""
        return self._god_mode_enabled

    def enable_god_mode(self) -> None:
        self._god_mode_enabled = True
        # Recreate all existing pipelines with god_mode=True
        with self._lock:
            for bed_id, pipeline in self._pipelines.items():
                pipeline._injector = GodModeInjector.get()

    def on_sample(self, bed_id: str, fhr_norm: float, uc_norm: float) -> None:
        """
        Non-blocking. Called from ReplayEngine (event loop thread) at 4 Hz.
        Submits work to ThreadPoolExecutor so that PatchTST inference (every 24 samples)
        does NOT block the async event loop. Deque appends are fast; inference (~50ms) is not.
        """
        pipeline = self._pipelines.get(bed_id)
        if pipeline:
            self._executor.submit(self._process_and_broadcast, pipeline, fhr_norm, uc_norm)

    def _process_and_broadcast(self, pipeline: "SentinelRealtime",
                               fhr_norm: float, uc_norm: float) -> None:
        """Runs in ThreadPoolExecutor thread — CPU-heavy path is off the event loop."""
        state = pipeline.on_new_sample(fhr_norm, uc_norm)
        if state:
            # push() is synchronous and thread-safe (uses queue.Queue.put_nowait).
            # Do NOT wrap in run_coroutine_threadsafe — push is NOT a coroutine.
            self._broadcaster.push(state)

    def get_pipeline(self, bed_id: str) -> "SentinelRealtime | None":
        return self._pipelines.get(bed_id)

    def set_beds(self, bed_configs: list[dict], engine: ReplayEngine) -> None:
        """Atomically replace bed configuration (max 16)."""
        ...

    def get_bed_states(self) -> list[BedState]:
        """Returns latest BedState for all active beds."""
        ...
```

### `api/services/broadcaster.py`

```python
class AsyncBroadcaster:
    """
    Thread-safe queue → async WebSocket push.
    PipelineManager pushes BedState objects (thread context).
    Broadcaster drains queue in async event loop.
    """

    def __init__(self): ...

    def push(self, state: BedState) -> None:
        """Thread-safe: called from pipeline callbacks."""
        self._queue.put_nowait(asdict(state))

    async def start(self) -> None:
        """Start drain loop + heartbeat."""
        ...

    async def register(self, ws: WebSocket) -> str: ...
    async def unregister(self, client_id: str): ...
    async def _drain_loop(self) -> None:
        """Reads queue → sends to all connected WebSocket clients."""
        ...
```

### REST API Endpoints

#### `/api/simulation`
| Method | Path | תיאור |
|--------|------|-------|
| GET | `/api/simulation/status` | מצב (running, bed_count, tick_count) |
| POST | `/api/simulation/start` | הפעל מחדש |
| POST | `/api/simulation/stop` | עצור |
| POST | `/api/simulation/pause` | השהה |
| POST | `/api/simulation/resume` | חדש |

#### `/api/beds`
| Method | Path | תיאור |
|--------|------|-------|
| GET | `/api/beds` | רשימת כל הלידות + BedState אחרוני |
| GET | `/api/beds/{bed_id}` | snapshot מלא של לידה |
| GET | `/api/beds/{bed_id}/history` | היסטוריית FHR/UC (עד 30 דקות, denormalized) |
| POST | `/api/beds/config` | שינוי config (bed_count 1-16, recording assignment) |

#### `/api/health`
| Method | Path | תיאור |
|--------|------|-------|
| GET | `/api/health` | בדיקת זמינות — `{"status":"ok","models_loaded":true,"active_beds":4}` |

#### `/ws/stream`
- WebSocket — push-based, כל `BedState` עם כל לידה
- פרוטוקול — batch של כל הלידות שהתעדכנו:
  ```json
  {
    "type": "batch_update",
    "timestamp": 1741168800.0,
    "updates": [
      {
        "bed_id": "bed_01",
        "recording_id": "1023",
        "risk_score": 0.72,
        "alert": true,
        "window_prob": 0.65,
        "fhr_latest": [138.4, 139.1, 141.0, ...],
        "uc_latest": [12.0, 15.3, 18.0, ...],
        "baseline_bpm": 140.0,
        "is_tachycardia": 0.0,
        "is_bradycardia": 0.0,
        "variability_amplitude_bpm": 8.5,
        "variability_category": 2.0,
        "n_late_decelerations": 2,
        "n_variable_decelerations": 1,
        "n_prolonged_decelerations": 0,
        "max_deceleration_depth_bpm": 28.0,
        "sinusoidal_detected": false,
        "tachysystole_detected": false,
        "elapsed_seconds": 1320.0,
        "warmup": false
      }
    ]
  }
  ```
  > **batch_update** — ב-tick אחד של 6 שניות ייתכן שמספר לידות מתעדכנות. שליחת message אחד עם array מפחיתה latency ו-overhead.

### `api/models/schemas.py`

```python
class BedUpdate(BaseModel):
    """Single-bed update. Transmitted inside BatchUpdate.updates list."""
    bed_id: str
    recording_id: str
    risk_score: float                       # [0, 1]
    alert: bool
    window_prob: float                      # latest PatchTST window prob
    fhr_latest: list[float]                 # last 24 samples in BPM (denormalized) — 1 full stride
    uc_latest: list[float]                  # last 24 samples in mmHg (denormalized)
    # Clinical features — exact names matching CLINICAL_FEATURE_NAMES:
    baseline_bpm: float
    is_tachycardia: float
    is_bradycardia: float
    variability_amplitude_bpm: float
    variability_category: float
    n_late_decelerations: int
    n_variable_decelerations: int
    n_prolonged_decelerations: int
    max_deceleration_depth_bpm: float
    sinusoidal_detected: bool
    tachysystole_detected: bool
    elapsed_seconds: float
    warmup: bool


class BatchUpdate(BaseModel):
    """WebSocket message — one per tick, contains all updated beds."""
    type: Literal["batch_update"] = "batch_update"
    timestamp: float
    updates: list[BedUpdate]


class SimulationStatus(BaseModel):
    running: bool
    paused: bool
    bed_count: int
    tick_count: int
    elapsed_seconds: float


class BedConfig(BaseModel):
    bed_count: int = Field(ge=1, le=16)
    assignments: list[dict] | None = None  # [{"bed_id": "bed_01", "recording_id": "1023"}]
```

### `api/services/model_loader.py`

```python
def load_production_models():
    """
    Loaded once at startup. Returns:
      models: list[PatchTST]        — 5 folds, eval mode, ClassificationHead attached
      scaler: StandardScaler
      lr_model: LogisticRegression
      config: dict  — production_config.json
    """
    import pickle, json, torch
    from src.model.patchtst import PatchTST, load_config
    from src.model.heads import ClassificationHead

    cfg = load_config("config/train_config.yaml")
    with open("artifacts/production_config.json") as f:
        prod_cfg = json.load(f)

    models = []
    for fold in range(prod_cfg["n_folds"]):   # 5
        path = prod_cfg["weights"][fold]      # e.g. "weights/fold0_best_finetune.pt"

        model = PatchTST(cfg)
        # ⚠ REQUIRED: attach ClassificationHead BEFORE load_state_dict
        # (state dict contains head weights; PatchTST.head defaults to None)
        # d_in = n_patches(73) * d_model(128) * n_channels(2) = 18688
        model.replace_head(ClassificationHead(d_in=18688, n_classes=2, dropout=0.2))

        state = torch.load(path, map_location="cpu", weights_only=True)
        model.load_state_dict(state)
        model.eval()
        models.append(model)

    with open("artifacts/production_scaler.pkl", "rb") as f:
        scaler = pickle.load(f)
    with open("artifacts/production_lr.pkl", "rb") as f:
        lr_model = pickle.load(f)

    return models, scaler, lr_model, prod_cfg
```

### CORS + Dev Networking

**בעיה:** בסביבת פיתוח, backend רץ על `:8000` ו-frontend על `:5173`. `ws://${location.host}/ws/stream` ינסה להתחבר ל-`:5173` — חיבור ייכשל.

**FastAPI — הפעל CORS middleware:**
```python
# api/main.py
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],  # dev only; production = same-origin via nginx
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

**Vite — הגדר proxy לכל ה-API וה-WebSocket:**
```typescript
// frontend/vite.config.ts
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': 'http://localhost:8000',
      '/ws': {
        target: 'ws://localhost:8000',
        ws: true,            // WebSocket proxy
        changeOrigin: true,
      },
    },
  },
})
```

> **בפרודקשן** (Docker + nginx): ה-proxy ב-`nginx.conf` מטפל בניתוב — אין צורך ב-CORS כי הכל מאותו origin. ה-CORS middleware רלוונטי לסביבת dev בלבד.

---

## 5. שלב 4 — Frontend: React + lightweight-charts

### מבנה תיקיות

```
frontend/
├── index.html
├── package.json
├── vite.config.ts
├── tailwind.config.js
├── tsconfig.json
└── src/
    ├── main.tsx
    ├── App.tsx
    ├── types/
    │   └── index.ts          ← BedUpdate, SimulationStatus, etc.
    ├── services/
    │   ├── api.ts            ← REST client
    │   └── websocket.ts      ← WebSocket manager (singleton)
    ├── stores/
    │   ├── bedStore.ts       ← Zustand: bed data + ring buffers
    │   └── uiStore.ts        ← Zustand: grid size, selected bed, etc.
    ├── hooks/
    │   ├── useBedStream.ts   ← WebSocket → bedStore
    │   ├── useSimulation.ts  ← simulation control
    │   └── useCTGChart.ts    ← lightweight-charts instance management
    ├── components/
    │   ├── layout/
    │   │   ├── Layout.tsx    ← header + main content
    │   │   └── Header.tsx    ← title + controls + status
    │   ├── ward/
    │   │   ├── WardView.tsx  ← grid of BedCards
    │   │   ├── BedCard.tsx   ← single bed card
    │   │   ├── RiskGauge.tsx ← risk score bar (B&W)
    │   │   └── Sparkline.tsx ← mini CTG chart
    │   ├── detail/
    │   │   ├── DetailView.tsx    ← full-screen single bed
    │   │   ├── CTGChart.tsx      ← lightweight-charts dual pane
    │   │   ├── RiskTimeline.tsx  ← risk score over time
    │   │   └── FindingsPanel.tsx ← clinical findings
    │   └── common/
    │       ├── GridSelector.tsx  ← 1/4/9/16 toggle
    │       ├── ConnectionBadge.tsx
    │       └── AlertBanner.tsx
    └── utils/
        ├── ringBuffer.ts       ← typed ring buffer (frontend FHR/UC history)
        ├── chartConfig.ts      ← lightweight-charts defaults
        ├── chartUpdateBus.ts   ← event bus: bypasses React render cycle for chart updates
        └── chartHelpers.ts     ← data formatting helpers
```

### `types/index.ts`

```typescript
// types/index.ts — mirrors Python BedState / BatchUpdate exactly

export interface BedUpdate {
  bed_id: string
  recording_id: string
  risk_score: number              // [0, 1]
  alert: boolean
  window_prob: number             // latest PatchTST window P(acidemia)
  fhr_latest: number[]            // last 24 values in BPM (denormalized by backend) — 1 full stride
  uc_latest: number[]             // last 24 values in mmHg (denormalized by backend)
  // Clinical — exact names from CLINICAL_FEATURE_NAMES:
  baseline_bpm: number
  is_tachycardia: number          // 0 or 1
  is_bradycardia: number          // 0 or 1
  variability_amplitude_bpm: number
  variability_category: number    // 0=absent 1=minimal 2=moderate 3=marked
  n_late_decelerations: number
  n_variable_decelerations: number
  n_prolonged_decelerations: number
  max_deceleration_depth_bpm: number
  sinusoidal_detected: boolean
  tachysystole_detected: boolean
  elapsed_seconds: number
  warmup: boolean
}

export interface BatchUpdate {
  type: 'batch_update'
  timestamp: number
  updates: BedUpdate[]
}

export interface InitialStateMessage {
  type: 'initial_state'
  beds: BedUpdate[]   // full state of all beds on connect
}

export interface HeartbeatMessage {
  type: 'heartbeat'
  ts: number          // Unix timestamp (seconds)
}

/** Discriminated union of all possible WebSocket messages from server */
export type WSMessage = BatchUpdate | InitialStateMessage | HeartbeatMessage

export interface SimulationStatus {
  running: boolean
  paused: boolean
  bed_count: number
  tick_count: number
  elapsed_seconds: number
}
```

### State Management (Zustand)

```typescript
// stores/bedStore.ts

interface BedData {
  bedId: string
  recordingId: string
  riskScore: number
  alert: boolean
  windowProb: number
  fhrRing: RingBuffer<number>        // frontend ring buffer: last 10 min FHR in BPM (denormalized)
  ucRing: RingBuffer<number>         // frontend ring buffer: last 10 min UC in mmHg (denormalized)
  riskHistory: RingBuffer<{t: number, v: number}>   // risk score over time
  // Clinical fields — mirror BedUpdate exactly:
  baselineBpm: number
  isTachycardia: boolean
  isBradycardia: boolean
  variabilityAmplitudeBpm: number
  variabilityCategory: number        // 0=absent, 1=minimal, 2=moderate, 3=marked
  nLateDecelerations: number
  nVariableDecelerations: number
  nProlongedDecelerations: number
  maxDecelerationDepthBpm: number
  sinusoidalDetected: boolean
  tachysystoleDetected: boolean
  elapsedSeconds: number
  warmup: boolean
  lastUpdate: number
}

interface BedStore {
  beds: Map<string, BedData>
  connected: boolean
  updateFromWebSocket: (update: BedUpdate) => void
  setConnected: (v: boolean) => void
  reset: () => void
}
```

**עקרון ביצועים:** `updateFromWebSocket` רק **מוסיף** ל-ring buffers. לא מחליף כל ה-array.  
ה-lightweight-charts מקבל `series.update(point)` — לא `setData([...])`.

### Ring Buffer (Frontend)

```typescript
// utils/ringBuffer.ts

export class RingBuffer<T> {
  private buf: T[]
  private head = 0
  readonly size: number

  constructor(size: number) {
    this.size = size
    this.buf = new Array(size).fill(0)
  }

  push(val: T): void {
    this.buf[this.head % this.size] = val
    this.head++
  }

  toArray(): T[] {
    if (this.head < this.size) return this.buf.slice(0, this.head)
    const idx = this.head % this.size
    return [...this.buf.slice(idx), ...this.buf.slice(0, idx)]
  }

  last(): T | undefined {
    return this.head > 0 ? this.buf[(this.head - 1) % this.size] : undefined
  }
}
```

גדלים:
- `fhrRing`: 2400 samples = 10 דקות (לview מלא בDetailView)
- `ucRing`: 2400 samples
- `riskHistory`: 600 נקודות = 60 דקות × 10 (כל 6 שניות)

### Pages

#### WardView

```
┌─────────────────────────────────────────────────────────────────┐
│  SentinelFetal2   [● LIVE]   Beds: 8/16   [1][4][9][16]   [⚙]  │
├─────────────────────────────────────────────────────────────────┤
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐          │
│  │ bed_01   │ │ bed_02   │ │ bed_03   │ │ bed_04   │          │
│  │ #1023    │ │ #1045    │ │ #1073    │ │ #1011    │          │
│  │ ▓▓▓▒░░░░│ │ ▓▓▓▓▓▒░░│ │ ▓░░░░░░░│ │ ▓▓░░░░░░│ [risk]   │
│  │ [CTG ─] │ │ [CTG ─] │ │ [CTG ─]  │ │ [CTG ─] │          │
│  │ 142 bpm │ │ 138 bpm │ │ 145 bpm  │ │ 131 bpm │          │
│  │  15 mmHg│ │  42 mmHg│ │   8 mmHg │ │  28 mmHg│          │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘          │
│   ...                                                           │
└─────────────────────────────────────────────────────────────────┘
```

**Grid Selector:** כפתורים 1 / 4 / 9 / 16 — משנה `gridColumns` ב-uiStore  
**מיון:** לפי `risk_score` יורד (הכי מסוכנת למעלה-שמאל)  
**Alert:** כרטיס של לידה עם `alert=true` מקבל border עבה + bold text  

#### BedCard

```
┌────────────────────────────────────┐
│ bed_01          #1023    ● WARMUP  │  ← כאשר warmup=true
│ ────────────────────────────────── │
│  [       CTG Sparkline         ]   │  lightweight-charts embed
│  [  ─────────────────────────  ]   │  FHR top + UC bottom (mini)
│ ────────────────────────────────── │
│  FHR  142 bpm   UC  15 mmHg       │
│  Baseline 140   Var 8.5 bpm       │
│ ────────────────────────────────── │
│  Risk  ███████████░░░░  0.72  ⚠️  │  ← alert visual: bold + border
│ ────────────────────────────────── │
│  Late:2  Var:1  Prol:0  Depth:28  │
└────────────────────────────────────┘
```

#### DetailView

```
┌──────────────────────────────────────────────────────────────────────┐
│ ← Ward   bed_01 (#1023)   00:22:15   ● LIVE   Risk: 0.72  ⚠️ ALERT  │
├──────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  ┌─── CTG Monitor (last 10 min) ──────────────────── [Fit][LIVE] ─┐ │
│  │ 210 ─                                                           │ │
│  │ 160 ─ ─────────────────────────/─────────────────────────────  │ │
│  │ 110 ─                                                           │ │
│  │  50 ─                                                           │ │
│  │  ─── FHR ─────────────────────────────────────────────────── ─ │ │
│  │ 100 ─           ╭──╮       ╭──╮       ╭───╮       ╭──╮         │ │
│  │  50 ─           │  │       │  │       │   │       │  │         │ │
│  │   0 ─ ──────────╯  ╰───────╯  ╰───────╯   ╰───────╯  ╰──────── │ │
│  │  ─── UC ─────────────────────────────────────────────────────── │ │
│  └────────────────────────────────────────────────────────────────┘ │
│                                                                      │
│  ┌─── Risk Score History ─────────────────────────────────────────┐ │
│  │  1.0 ─                                                          │ │
│  │  0.5 ─ ──────────────────────────────/─────────────────────── ─ │
│  │  0.0 ─ threshold ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─  │ │
│  └────────────────────────────────────────────────────────────────┘ │
│                                                                      │
│  ┌─── Clinical Findings ──────────────┐  ┌─── Alert History ──────┐  │
│  │  Baseline:     140 bpm            │  │  12:34:15 ALERT 0.72   │  │
│  │  Tachycardia:  No                 │  │  12:28:09 ALERT 0.68   │  │
│  │  Bradycardia:  No                 │  │  12:22:03 clear  0.41   │  │
│  │  Variability:  8.5 bpm (moderate) │  │                         │  │
│  │  Late decels:  2                  │  │                         │  │
│  │  Variable:     1                  │  │                         │  │
│  │  Prolonged:    0                  │  │                         │  │
│  │  Max depth:    28.0 bpm           │  │                         │  │
│  │  Sinusoidal:   No                 │  │                         │  │
│  │  Tachysystole: No                 │  │                         │  │
│  └────────────────────────────────────┘  └─────────────────────────┘  │
└──────────────────────────────────────────────────────────────────────┘
```

### `utils/chartUpdateBus.ts` (חדש)

```typescript
// utils/chartUpdateBus.ts
// Decouples CTG chart updates from React render cycle.
// WebSocket frame → chartUpdateBus.publish() → chart series.update() via ref.
// This avoids a Store → re-render → effect chain that can call series.update() twice
// (e.g., under React Strict Mode double-invoke, or when unrelated state changes
// cause the chart component to re-render in the same tick).

type ChartCallback = (fhrVals: number[], ucVals: number[], tStart: number) => void

class ChartUpdateBus {
  private subs = new Map<string, ChartCallback>()

  subscribe(bedId: string, cb: ChartCallback): () => void {
    this.subs.set(bedId, cb)
    return () => this.subs.delete(bedId)
  }

  publish(bedId: string, fhrVals: number[], ucVals: number[], tStart: number): void {
    this.subs.get(bedId)?.(fhrVals, ucVals, tStart)
  }
}

// Singleton — one bus per app
export const chartUpdateBus = new ChartUpdateBus()
```

### `hooks/useBedStream.ts`

```typescript
import type { BedUpdate, WSMessage } from '../types'

export function useBedStream() {
  const updateFromWebSocket = useBedStore(s => s.updateFromWebSocket)
  const setConnected = useBedStore(s => s.setConnected)

  useEffect(() => {
    let ws: WebSocket
    let reconnectTimer: number
    let attempt = 0

    function connect() {
      ws = new WebSocket(`ws://${location.host}/ws/stream`)

      ws.onopen = () => {
        setConnected(true)
        attempt = 0
      }

      ws.onclose = () => {
        setConnected(false)
        const delay = Math.min(500 * 2 ** attempt, 10_000)
        attempt++
        reconnectTimer = window.setTimeout(connect, delay)
      }

      ws.onmessage = (event) => {
        const msg = JSON.parse(event.data) as WSMessage   // typed discriminated union

        if (msg.type === 'initial_state') {
          useBedStore.getState().initializeFromSnapshot(msg.beds)
          return
        }

        if (msg.type === 'batch_update') {
          for (const update of msg.updates as BedUpdate[]) {
            // 1. Update React store (for WardView cards, risk scores, clinical fields)
            updateFromWebSocket(update)

            // 2. Push CTG samples DIRECTLY to chart — bypass React re-render entirely.
            //    chartUpdateBus listeners call series.update() via ref — O(1), no re-render.
            //    ⚠ Do NOT derive chart updates from store subscription: a store change
            //    triggers a component re-render which re-runs effects → series.update()
            //    called a second time with the same data → chart shows zigzag artifacts.
            const tStart = update.elapsed_seconds - update.fhr_latest.length * 0.25
            chartUpdateBus.publish(update.bed_id, update.fhr_latest, update.uc_latest, tStart)
          }
        }

        if (msg.type === 'heartbeat') {
          // update last-seen timestamp for stale detection
          useBedStore.getState().setHeartbeat(msg.ts)
        }
      }
    }

    connect()
    return () => {
      clearTimeout(reconnectTimer)
      ws?.close()
    }
  }, [])
}
```

### CTGChart (lightweight-charts)

```typescript
// hooks/useCTGChart.ts
import { createChart, IChartApi, ISeriesApi } from 'lightweight-charts'

export function useCTGChart(containerRef: RefObject<HTMLDivElement>, bedId: string) {
  const chartRef = useRef<IChartApi | null>(null)
  const fhrSeriesRef = useRef<ISeriesApi<'Line'> | null>(null)
  const ucSeriesRef = useRef<ISeriesApi<'Line'> | null>(null)

  useEffect(() => {
    if (!containerRef.current) return

    const chart = createChart(containerRef.current, {
      layout: {
        background: { color: '#ffffff' },
        textColor: '#111827',
      },
      grid: {
        vertLines: { color: '#f3f4f6' },
        horzLines: { color: '#f3f4f6' },
      },
      rightPriceScale: { borderColor: '#e5e7eb' },
      timeScale: { borderColor: '#e5e7eb' },
    })

    // FHR — שחור, pane עליון
    const fhrSeries = chart.addLineSeries({
      color: '#111827',
      lineWidth: 1.5,
      priceScaleId: 'right',
    })
    fhrSeries.applyOptions({
      autoscaleInfoProvider: () => ({
        priceRange: { minValue: 50, maxValue: 210 },
      }),
      priceScale: { scaleMargins: { top: 0.05, bottom: 0.55 } },
    })

    // UC — אפור כהה, pane תחתון
    const ucSeries = chart.addLineSeries({
      color: '#6b7280',
      lineWidth: 1,
      priceScaleId: 'left',
    })
    ucSeries.applyOptions({
      autoscaleInfoProvider: () => ({
        priceRange: { minValue: 0, maxValue: 100 },
      }),
      priceScale: { scaleMargins: { top: 0.55, bottom: 0.05 } },
    })

    chartRef.current = chart
    fhrSeriesRef.current = fhrSeries
    ucSeriesRef.current = ucSeries

    return () => chart.remove()
  }, [])

  // Subscribe to chartUpdateBus — NOT to React state.
  // This guarantees series.update() is called exactly once per WebSocket frame,
  // regardless of how many times the component re-renders.
  useEffect(() => {
    const unsubscribe = chartUpdateBus.subscribe(
      bedId,
      (fhrVals: number[], ucVals: number[], tStart: number) => {
        if (!fhrSeriesRef.current || !ucSeriesRef.current) return
        fhrVals.forEach((v, i) => {
          const t = tStart + i * 0.25
          fhrSeriesRef.current!.update({ time: t as Time, value: v })
          ucSeriesRef.current!.update({ time: t as Time, value: ucVals[i] })
        })
      }
    )
    return unsubscribe
  }, [bedId])  // only re-subscribe if bedId changes

  return { chart: chartRef }
}
```

**עקרון מרכזי:** `series.update()` מוסיף נקודה אחת — O(1), לא O(n).  
אף פעם לא `setData()` אחרי ה-init הראשוני.  
**עקרון ביצועים נוסף:** העדכון לגרף מגיע ישירות מ-`chartUpdateBus` (event-driven), לא דרך Zustand store → re-render → effect.  
אין סכנה של קריאה כפולה ל-`series.update()` בגלל React Strict Mode או re-render על state לא-קשור.

### `components/ward/RiskGauge.tsx`

```tsx
// Risk score bar — B&W עיצוב
// 0.0 → אפור בהיר | 0.5 → אפור כהה | >threshold → שחור bold

export function RiskGauge({ score, threshold, alert }: Props) {
  const pct = Math.round(score * 100)
  const barWidth = `${pct}%`
  const barColor = alert ? '#111827' : score > 0.35 ? '#374151' : '#d1d5db'

  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-2 bg-gray-100 rounded-full overflow-hidden">
        <div
          style={{ width: barWidth, backgroundColor: barColor }}
          className="h-full transition-all duration-500 rounded-full"
        />
      </div>
      <span className={`text-xs font-mono font-semibold w-8 text-right ${
        alert ? 'text-black font-bold' : 'text-gray-600'
      }`}>
        {score.toFixed(2)}
      </span>
      {alert && <span className="text-xs font-bold text-black">⚠</span>}
    </div>
  )
}
```

---

## 6. שלב 5 — אינטגרציה וטסטים

### סדר ביצוע (dependencies)

```
שלב 1: src/inference/pipeline.py          ← עצמאי, תלוי ב-src/ קיים
   ↓
שלב 2: generator/replay.py                ← עצמאי, תלוי ב-data/recordings/
   ↓
שלב 3: api/ (backend FastAPI)             ← תלוי ב-1, 2
   ↓
שלב 4: frontend/ (React)                  ← תלוי ב-3
   ↓
שלב 5: אינטגרציה: הרצה מלאה              ← כולם ביחד
```

### Smoke test — כל שלב

#### שלב 1
```bash
python -c "
from src.inference.pipeline import SentinelRealtime
import numpy as np, pickle, json

models, scaler, lr, cfg = ...  # load
p = SentinelRealtime('bed_01', '1023', models, scaler, lr, cfg)

# simulate 2000 samples (> 1800 warmup)
# ⚠ Values MUST be normalized [0,1]: FHR=(bpm-50)/160, UC=mmHg/100
for i in range(2000):
    fhr_norm = (140.0 + np.random.randn() - 50.0) / 160.0   # ≈ 0.5625
    uc_norm  = 15.0 / 100.0                                  # = 0.15
    state = p.on_new_sample(fhr_norm, uc_norm)
    if state:
        print(f'Got state: risk={state.risk_score:.3f} warmup={state.warmup}')
        break
"
```

#### שלב 2
```bash
python -c "
import asyncio
from pathlib import Path
from generator.replay import ReplayEngine

samples = []
def cb(bed_id, fhr, uc): samples.append((bed_id, fhr, uc))

async def test():
    e = ReplayEngine(Path('data/recordings'), cb)
    e.add_bed('bed_01', '1001')
    task = asyncio.create_task(e.run())   # run() is the public async API
    await asyncio.sleep(5.0)              # let it run for 5 real seconds
    e.stop()
    await task
    print(f'Got {len(samples)} samples from bed_01')  # expect ~80 (4Hz × 20 samples/sec)

asyncio.run(test())
"
```

#### שלב 3
```bash
uvicorn api.main:app --reload --port 8000
# בטרמינל נפרד:
curl http://localhost:8000/api/simulation/status
curl http://localhost:8000/api/beds
```

#### שלב 4
```bash
cd frontend && npm install && npm run dev
# פתח: http://localhost:5173
```

#### שלב 5 — Integration
```bash
# terminal 1:
uvicorn api.main:app --port 8000
# terminal 2:
cd frontend && npm run dev
# ציפי: 4 כרטיסי לידה מתעדכנים כל 6 שניות, גרפים זורמים
```

### בדיקות ביצועים — 16 לידות

```bash
python scripts/perf_test_16beds.py
# מצפה:
# - CPU ≤ 40% (16 beds × ~50ms PatchTST / 6sec interval)
# - Memory ≤ 1GB
# - WebSocket lag < 200ms
# - No dropped frames in frontend (60fps)
```

---

## 7. מבנה קבצים סופי

```
SentinelFetal2-Production/
│
├── src/                          ← קיים ✅ + חדש
│   ├── model/                    ← ✅ קיים
│   ├── data/                     ← ✅ קיים
│   ├── inference/
│   │   ├── sliding_window.py     ← ✅ קיים
│   │   ├── alert_extractor.py    ← ✅ קיים
│   │   └── pipeline.py           ← 🔨 חדש (שלב 1)
│   ├── rules/                    ← ✅ קיים
│   └── features/                 ← ✅ קיים
│
├── generator/
│   └── replay.py                 ← 🔨 חדש (שלב 2)
│
├── api/                          ← 🔨 חדש (שלב 3)
│   ├── main.py
│   ├── config.py
│   ├── dependencies.py
│   ├── models/schemas.py
│   ├── routers/
│   │   ├── simulation.py
│   │   ├── beds.py
│   │   └── websocket.py
│   └── services/
│       ├── pipeline_manager.py
│       ├── broadcaster.py
│       └── model_loader.py
│
├── frontend/                     ← 🔨 חדש (שלב 4)
│   ├── package.json
│   ├── vite.config.ts
│   ├── tailwind.config.js
│   └── src/
│       ├── App.tsx
│       ├── types/index.ts
│       ├── services/
│       ├── stores/
│       ├── hooks/
│       ├── components/
│       │   ├── layout/
│       │   ├── ward/
│       │   ├── detail/
│       │   └── common/
│       └── utils/
│
├── artifacts/                    ← ✅ קיים
├── config/                       ← ✅ קיים
├── data/                         ← ✅ קיים
├── weights/                      ← ✅ קיים
├── docs/                         ← ✅ קיים
│   ├── system_summary_he.md
│   └── PLAN.md                   ← 📄 זה המסמך
├── pyproject.toml                 ← ✅ מקור הסמכות לתלויות Python
└── uv.lock                        ← ✅ lockfile reproducible ל-uv
```

---

## 8. עקרונות עיצוב

### צבע — שחור ולבן בלבד

| אלמנט | ערך CSS | שימוש |
|-------|---------|-------|
| רקע | `#ffffff` | כל הדפים |
| טקסט ראשי | `#111827` | כותרות, ערכים |
| טקסט משני | `#6b7280` | תוויות, metadata |
| Borders | `#e5e7eb` | cards, dividers |
| Risk bar — רגיל | `#d1d5db` | score < 0.35 |
| Risk bar — מוגבה | `#374151` | score 0.35–threshold |
| Risk bar — alert | `#111827` | score > threshold |
| CTG FHR line | `#111827` | |
| CTG UC line | `#6b7280` | |
| Alert border | `2px solid #111827` | card עם alert=true |

**אין צבע** — לא כחול, לא אדום, לא ירוק. אורגניזציה ויזואלית ע"י:
- מרווח, גדלי font, עובי border
- lowercase / UPPERCASE
- font-weight: regular → **bold**

### Typography

```css
/* Tailwind classes */
font-family: ui-monospace (ערכים), system-ui (טקסט)
/* ערכי FHR/UC: font-mono */
/* כותרות: font-semibold */
/* ערכי סיכון: font-bold font-mono */
```

### Animation

- `transition-all duration-500` על risk bar
- `transition-colors duration-200` על hover
- **אין** pulse/blink — מבלבל בסביבה רפואית
- חריג: `animate-pulse` על `● LIVE` badge (עדין, עגול קטן)

---

## 9. ביצועים: 16 לידות במקביל

### בעיה: PatchTST inference CPU-heavy

- כל forward pass: ~50ms על CPU (inference על חלון 1800×2)
- 16 לידות × 50ms = 800ms אם sequential
- אבל: כל לידה מבצעת inference כל **6 שניות** — לא בו-זמנית

### פתרון: ThreadPoolExecutor + staggered inference

`SentinelRealtime.on_new_sample()` מחזיר `BedState | None`. כאשר הוא מחזיר `BedState` (כל 24 samples = 6 שניות לאחר warmup), הוא כולל inference של PatchTST. כדי לא לחסום את async event loop, ה-`PipelineManager` מריץ את קריאות ה-PatchTST בתוך `ThreadPoolExecutor`:

```python
# api/services/pipeline_manager.py
from concurrent.futures import ThreadPoolExecutor

class PipelineManager:
    def __init__(self, ...):
        # 4 workers: at most 4 concurrent PatchTST inferences (~200ms total vs 800ms sequential)
        self._executor = ThreadPoolExecutor(max_workers=4)
        # Note: _loop is NOT needed. push() is synchronous (queue.put_nowait);
        # no asyncio bridge is required from the thread pool.

    def on_sample(self, bed_id: str, fhr_norm: float, uc_norm: float) -> None:
        """
        Non-blocking — returns immediately. Called at 4 Hz from event loop.
        ⚠ CRITICAL: do NOT call pipeline.on_new_sample() directly here.
        Every 24th call triggers PatchTST inference (~50ms). Calling it synchronously
        inside the async loop would freeze WebSocket delivery for up to 800ms (16 beds).
        """
        pipeline = self._pipelines.get(bed_id)
        if pipeline:
            self._executor.submit(self._process_and_broadcast, pipeline, fhr_norm, uc_norm)

    def _process_and_broadcast(self, pipeline, fhr_norm: float, uc_norm: float) -> None:
        """Thread pool worker. Inference + broadcast — off the event loop."""
        state = pipeline.on_new_sample(fhr_norm, uc_norm)
        if state:
            # push() is thread-safe (queue.Queue.put_nowait) — call directly.
            self._broadcaster.push(state)
```

עם 16 לידות ו-staggered timing (לידות מתחילות בזמנים שונים):
- בו-זמנית לכל היותר 4 inference → latency מקסימלית 200ms
- UI מקבל update כל 6 שניות per bed

### Frontend

- כל BedCard מ-wrapped ב-`React.memo` — re-render רק כשהנתונים שלה משתנים
- Ring buffers (Zustand store) מאפשרים immutable push בלי re-create whole array
- `lightweight-charts`:  `series.update()` — O(1) append, no re-render
- Grid של 16 כרטיסים: Virtualization לא נדרש (16 DOM nodes קל)

### WebSocket: Batch Update

כל tick (6 שניות) ה-`AsyncBroadcaster` שולח **message אחד** עם כל הלידות שהתעדכנו:
```json
{
  "type": "batch_update",
  "timestamp": 1741168800.0,
  "updates": [
    { "bed_id": "bed_01", "risk_score": 0.72, ... },
    { "bed_id": "bed_02", "risk_score": 0.31, ... }
  ]
}
```
לא 16 messages נפרדים — מפחית latency ו-overhead.

### זיכרון

| component | גודל |
|-----------|------|
| RingBuffer per bed (backend): 7200 × 2 × float32 | ~57 KB |
| 16 beds | ~900 KB |
| 5 PatchTST models | ~50 MB |
| Frontend ring buffers: 2400 × 3 channels × float64 | ~58 KB/bed |
| 16 beds frontend | ~930 KB |
| **סה"כ** | **<100 MB** |

---

## נספח: תלויות חדשות להתקנה

### Python (`pyproject.toml` + `uv.lock`)
התלויות מנוהלות כיום דרך `uv`, כאשר `pyproject.toml` הוא מקור הסמכות ו-`uv.lock` מקבע את סביבת ההרצה.

```bash
uv sync --locked
```

התלויות המרכזיות כוללות `fastapi`, `uvicorn[standard]`, `pydantic`, `pydantic-settings`, `websockets`, `torch==2.2.2` מאינדקס CPU של PyTorch, `numpy<2`, ו-`scikit-learn==1.6.1`.

> **הערה:** `dash`, `plotly`, `dash-bootstrap-components` אינם חלק ממסלול ההרצה הראשי של FastAPI + React. אם צריך אותם למסך legacy, הם שייכים ל-optional dependencies ולא לקובץ requirements נפרד.

### Node.js (`frontend/package.json`)
```json
{
  "dependencies": {
    "react": "^18.3",
    "react-dom": "^18.3",
    "react-router-dom": "^6.22",
    "zustand": "^4.5",
    "lightweight-charts": "^4.1",
    "react-hot-toast": "^2.4"
  },
  "devDependencies": {
    "typescript": "^5.4",
    "vite": "^5.2",
    "@vitejs/plugin-react": "^4.3",
    "tailwindcss": "^3.4",
    "autoprefixer": "^10.4",
    "postcss": "^8.4"
  }
}
```

---

## נספח: הערות טכניות

### `bdecf_threshold` ב-production_config
`production_config.json` מכיל `"bdecf_threshold": 8.0`. ערך זה משמש ב-`src/rules/decelerations.py` לסינון דצלרציות לפי עומק מינימלי. הוא לא חלק מ-25 הפיצ'רים ולא מוצהר ב-`BedState` — הוא פנימי לחישוב הכלים.

### `ALERT_THRESHOLD` vs `best_at`
- `src/inference/alert_extractor.py` מגדיר `ALERT_THRESHOLD = 0.4` (hardcoded, Deviation S11)
- `production_config.json` מגדיר `"best_at": 0.5`
- **בpipeline יש להשתמש ב-`config["best_at"]` = 0.5** — זה הסף שבו LR אומן. שימוש ב-0.4 ייצור features שונות ממה שאומן.
- ה-`ALERT_THRESHOLD` של 0.4 בקובץ alert_extractor רלוונטי רק לסביבת הפיתוח/עברית הישנה. Production overrides זה ב-config.

### `INFERENCE_STRIDE` בproduction
- `sliding_window.py` מגדיר `INFERENCE_STRIDE_REPRO=1`, `INFERENCE_STRIDE_RUNTIME=60`
- **بالproduction pipeline משתמשים ב-stride=24** (מ-production_config `"inference_stride":24`)
- stride=24 הוא הסטרייד שבו LR אומן ← חייב להיות זהה ב-inference
- לא קוראים ל-`inference_recording()` מ-sliding_window.py — קוראים ישירות לmodel.forward() על החלון הנוכחי

---

## 10. God Mode — שליטה ידנית והזרקת אירועים

**מצב:** תכנון | **קדימות:** אחרי השלמת שלב 3 (Backend FastAPI)

---

### 10.1 מטרה ועיקרון

God Mode מאפשר לשלוט ידנית על מה שהמערכת "רואה" ומדווחת עבור יולדת ספציפית.  
מכיוון שהמערכת פועלת על נתוני replay (לא נתוני חולים אמיתיים), ישנן שתי אפשרויות:

1. **הזרקה ויזואלית:** להחדיר patch סינתטי לאות ה-CTG עצמו כך שהאות נראה כמו אירוע אמיתי
2. **Override ישיר של Features:** לדאוג שה-feature vector שמגיע ל-LR "יראה" כאילו האירוע קיים — גם אם האות עצמו לא מכיל אותו

**הגישה הנבחרת: שכבת Override על Features + Patch סינתטי אופציונלי לגרף.**

זה מבטיח:
- ✅ זיהוי מובטח תמיד (ללא תלות ב-PatchTST על נתונים סינתטיים)
- ✅ ביצועים מלאים נשמרים — כל לידות השגרה לא נוגעות ב-God Mode
- ✅ ציר הזמן מדויק — מתי התחיל, מתי נגמר, האם עדיין פעיל
- ✅ הסבר מפורט — מה זוהה ולמה

---

### 10.2 ארכיטקטורת God Mode

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        God Mode Architecture                            │
│                                                                         │
│  REST API: POST /api/god-mode/inject                                    │
│  ┌─────────────────────────────────────┐                                │
│  │  GodModeInjector (singleton)        │←── locks per bed               │
│  │  events: dict[bed_id → list[Event]] │                                │
│  └────────────────┬────────────────────┘                                │
│                   │ has_active_events() — O(1) per bed                   │
│                   ▼                                                     │
│  SentinelRealtime._compute_full_state()                                 │
│   1. extract_clinical_features(ring) → clin_list (רגיל)                │
│   2. extract_recording_features(window_scores) → pt_feats (רגיל)       │
│   3. [god mode check] → override: elevate matching fields               │
│   4. assemble 25-feature vector → LR → risk_score                      │
│   5. attach EventAnnotations to BedState                               │
│                   │                                                     │
│                   ▼                                                     │
│  BedState (מוגדל):                                                      │
│   + god_mode_active: bool                                               │
│   + active_events: list[EventAnnotation]   ← start/end + description   │
│                   │                                                     │
│                   ▼ WebSocket batch_update                              │
│  Frontend DetailView:                                                   │
│   + God Mode panel (כפתורי הזרקה)                                       │
│   + CTG chart markers (▼ start, ▲ end / ▼ ongoing)                     │
│   + Event journal (טבלת אירועים + ציר זמן)                             │
└─────────────────────────────────────────────────────────────────────────┘
```

---

### 10.3 טיפוסי הנתונים הברורים

#### `EventType` — סוגי האירועים הניתנים להזרקה

```python
# src/god_mode/types.py

from enum import Enum

class EventType(str, Enum):
    LATE_DECELERATIONS       = "late_decelerations"      # דיצלרציות מאוחרות
    VARIABLE_DECELERATIONS   = "variable_decelerations"  # דיצלרציות משתנות
    PROLONGED_DECELERATION   = "prolonged_deceleration"  # דיצלרציה ממושכת (≥2 דק')
    SINUSOIDAL_PATTERN       = "sinusoidal_pattern"      # דפוס סינוסואידלי
    TACHYSYSTOLE             = "tachysystole"            # תחסיסטולה
    BRADYCARDIA              = "bradycardia"             # ברדיקרדיה
    TACHYCARDIA              = "tachycardia"             # טכיקרדיה
    LOW_VARIABILITY          = "low_variability"         # תנודתיות נמוכה
    COMBINED_SEVERE          = "combined_severe"         # שילוב יוצר חמצת מלאה
```

#### `InjectionEvent` — רשומt ההזרקה

```python
# src/god_mode/types.py

from dataclasses import dataclass, field
import time
import uuid

@dataclass
class InjectionEvent:
    event_id:     str           # UUID אוטומטי
    bed_id:       str           # "bed_01"
    event_type:   EventType
    start_sample: int           # sample_count בעת ההזרקה
    end_sample:   int | None    # None = ongoing (עד לביטול ידני)
    description:  str           # "3 late decelerations injected, depth 25 bpm"
    severity:     float         # 0.5–1.0 (עוצמת האות override)
    created_at:   float = field(default_factory=time.time)
    # Signal swap fields (Phase 4 — god_mode_signal_plan.md)
    original_recording_id: str | None = None   # הקלטה מקורית לשחזור בסיום
    signal_swapped: bool = False               # האם הקלטה הוחלפה

    @classmethod
    def create(cls, bed_id, event_type, start_sample,
               duration_samples=None, severity=0.85, description=""):
        end = start_sample + duration_samples if duration_samples else None
        return cls(
            event_id=str(uuid.uuid4())[:8],
            bed_id=bed_id,
            event_type=event_type,
            start_sample=start_sample,
            end_sample=end,
            description=description or EventType(event_type).value,
            severity=severity,
        )
```

#### `EventAnnotation` — מה נשלח ל-frontend בכל BedState

```python
# src/god_mode/types.py

@dataclass
class EventAnnotation:
    event_id:        str
    event_type:      str
    start_sample:    int
    end_sample:      int | None
    still_ongoing:   bool            # True כשend_sample is None
    description:     str
    timeline_summary: str            # "החל 00:12:34 | משך: 00:03:20 | עדיין פעיל"
    detected_details: dict           # {feature: value} שנראו כחריגים
```

---

### 10.4 `GodModeInjector` — הלוגיקה המרכזית

```python
# src/god_mode/injector.py

import threading
from src.god_mode.types import InjectionEvent, EventAnnotation, EventType
from src.god_mode.overrides import build_feature_override

class GodModeInjector:
    """
    Thread-safe singleton.
    Holds active injection events per bed.
    Called from SentinelRealtime._compute_full_state() — must be O(1) when no events active.
    """
    _instance = None

    def __init__(self):
        self._events: dict[str, list[InjectionEvent]] = {}  # bed_id → events
        self._lock = threading.Lock()

    @classmethod
    def get(cls) -> "GodModeInjector":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    # ── Fast path ────────────────────────────────────────────────────────
    def has_active_events(self, bed_id: str, current_sample: int) -> bool:
        """O(1) fast check — no lock needed (reads list reference atomically)."""
        events = self._events.get(bed_id)
        if not events:
            return False
        return any(
            e.start_sample <= current_sample
            and (e.end_sample is None or current_sample <= e.end_sample)
            for e in events
        )

    # ── Override computation ──────────────────────────────────────────────
    def compute_override(
        self,
        bed_id: str,
        current_sample: int,
        clin_list: list[float],
        window_scores: list[tuple[int, float]],
        elapsed_seconds: float,
    ) -> tuple[list[float], list[tuple[int, float]], list[EventAnnotation]]:
        """
        Returns:
          - modified clin_list (clinical features overridden for active events)
          - modified window_scores (recent windows boosted)
          - list of EventAnnotation objects for UI
        Called only when has_active_events() is True.
        """
        with self._lock:
            events = [
                e for e in self._events.get(bed_id, [])
                if e.start_sample <= current_sample
                and (e.end_sample is None or current_sample <= e.end_sample)
            ]

        clin_out = list(clin_list)
        ws_out   = list(window_scores)
        annotations = []

        for event in events:
            # Override clinical features
            clin_out = build_feature_override(clin_out, event)

            # Boost recent window_scores so AI features also reflect problem
            min_prob = 0.5 + event.severity * 0.4  # severity 0.5→0.7, severity 1.0→0.9
            ws_out = [
                # s is the START index of a 1800-sample window.
                # The window covers [s, s+1800). We want to boost any window whose
                # END reaches or passes the event start — i.e. the event falls inside it.
                # ⚠ Wrong check: `s >= event.start_sample` (would boost only future windows,
                #    leaving the current injection invisible for 7.5 minutes!).
                (s, max(p, min_prob)) if s + 1800 >= event.start_sample else (s, p)
                for s, p in ws_out
            ]

            # Build annotation for UI
            duration_s  = None if event.end_sample is None else \
                          (event.end_sample - event.start_sample) / 4.0
            still_going = event.end_sample is None or current_sample <= event.end_sample
            start_hms   = _samples_to_hms(event.start_sample)
            dur_str     = "עדיין פעיל" if still_going else f"משך: {_sec_to_hms(duration_s)}"

            annotations.append(EventAnnotation(
                event_id        = event.event_id,
                event_type      = event.event_type.value,
                start_sample    = event.start_sample,
                end_sample      = event.end_sample,
                still_ongoing   = still_going,
                description     = event.description,
                timeline_summary= f"החל {start_hms} | {dur_str}",
                detected_details= _describe_override(clin_out, event.event_type),
            ))

        return clin_out, ws_out, annotations

    # ── Management API ────────────────────────────────────────────────────
    def add_event(self, event: InjectionEvent) -> None:
        with self._lock:
            self._events.setdefault(event.bed_id, []).append(event)

    def end_event(self, bed_id: str, event_id: str, current_sample: int) -> bool:
        """Mark an ongoing event as ended at current_sample."""
        with self._lock:
            for e in self._events.get(bed_id, []):
                if e.event_id == event_id and e.end_sample is None:
                    e.end_sample = current_sample
                    return True
        return False

    def get_event(self, bed_id: str, event_id: str) -> InjectionEvent | None:
        """עוזר לשחזר original_recording_id לפני end_event."""
        with self._lock:
            for e in self._events.get(bed_id, []):
                if e.event_id == event_id:
                    return e
        return None

    def clear_bed(self, bed_id: str) -> list[InjectionEvent]:
        """מחזיר את האירועים שנמחקו — לשחזור הקלטה."""
        with self._lock:
            return self._events.pop(bed_id, [])

    def get_events(self, bed_id: str) -> list[InjectionEvent]:
        with self._lock:
            return list(self._events.get(bed_id, []))
```

---

### 10.5 `overrides.py` — מפת ה-Override לכל סוג אירוע

```python
# src/god_mode/overrides.py
#
# Clinical feature list order (matches CLINICAL_FEATURE_NAMES):
# [0] baseline_bpm
# [1] is_tachycardia
# [2] is_bradycardia
# [3] variability_amplitude_bpm
# [4] variability_category
# [5] n_late_decelerations
# [6] n_variable_decelerations
# [7] n_prolonged_decelerations
# [8] max_deceleration_depth_bpm
# [9] sinusoidal_detected
# [10] tachysystole_detected

from src.god_mode.types import EventType, InjectionEvent

def build_feature_override(
    clin: list[float], event: InjectionEvent
) -> list[float]:
    """
    Returns a new clin list with features elevated according to event_type.
    Only raises values, never lowers them (additive overrides).
    """
    out = list(clin)
    s   = event.severity   # 0.5–1.0

    if event.event_type == EventType.LATE_DECELERATIONS:
        out[5]  = max(out[5],  round(3 + s * 4))   # n_late_decelerations    → 3–7
        out[8]  = max(out[8],  15 + s * 20)        # max_deceleration_depth  → 15–35 bpm

    elif event.event_type == EventType.VARIABLE_DECELERATIONS:
        out[6]  = max(out[6],  round(3 + s * 5))   # n_variable_decelerations → 3–8
        out[8]  = max(out[8],  20 + s * 25)        # depth → 20–45 bpm

    elif event.event_type == EventType.PROLONGED_DECELERATION:
        out[7]  = max(out[7],  1 + round(s))       # n_prolonged              → 1–2
        out[8]  = max(out[8],  30 + s * 20)        # depth → 30–50 bpm

    elif event.event_type == EventType.SINUSOIDAL_PATTERN:
        out[9]  = 1.0                               # sinusoidal_detected

    elif event.event_type == EventType.TACHYSYSTOLE:
        out[10] = 1.0                               # tachysystole_detected

    elif event.event_type == EventType.BRADYCARDIA:
        out[0]  = min(out[0], 100 - s * 10)        # baseline_bpm → 90–100
        out[2]  = 1.0                               # is_bradycardia

    elif event.event_type == EventType.TACHYCARDIA:
        out[0]  = max(out[0], 165 + s * 15)        # baseline_bpm → 165–180
        out[1]  = 1.0                               # is_tachycardia

    elif event.event_type == EventType.LOW_VARIABILITY:
        out[3]  = min(out[3], max(0.5, 2 - s * 1.5))  # amplitude_bpm → 0.5–2 bpm
        out[4]  = 0.0                               # category = absent

    elif event.event_type == EventType.COMBINED_SEVERE:
        # כל סממני חמצת מטבולית ביחד
        out[5]  = max(out[5],  3)                   # late decels
        out[7]  = max(out[7],  1)                   # prolonged
        out[8]  = max(out[8],  40.0)                # depth
        out[3]  = min(out[3],  2.0)                 # low variability
        out[4]  = 0.0                               # category absent
        out[10] = 1.0                               # tachysystole

    return out
```

---

### 10.6 שילוב ב-`SentinelRealtime` — נתיב הביצועים

**עקרון:** zero overhead על לידות ללא God Mode.

```python
# src/inference/pipeline.py — בתוך SentinelRealtime

def __init__(self, ..., god_mode: bool = False):
    ...
    # God mode is opt-in. GodModeInjector is a singleton — reference is cheap.
    self._god_mode = god_mode
    self._injector = GodModeInjector.get() if god_mode else None

def _compute_full_state(self) -> BedState:
    ...
    # ── normal feature extraction (unchanged) ────────────────────────────
    pt_feats = extract_recording_features(self._window_scores, threshold=at, ...)
    clin_list = extract_clinical_features(full_signal)
    all_probs = [p for _, p in self._window_scores]
    global_feat = [float(np.mean(all_probs)), float(np.std(all_probs))]

    # ── God Mode: O(1) check, only override when event active ────────────
    god_mode_active = False
    active_events:  list = []

    if (self._injector is not None
            and self._injector.has_active_events(self._bed_id, self._sample_count)):
        god_mode_active = True
        clin_list, window_scores_adj, active_events = self._injector.compute_override(
            bed_id         = self._bed_id,
            current_sample = self._sample_count,
            clin_list      = clin_list,
            window_scores  = self._window_scores,
            elapsed_seconds= self._sample_count / 4.0,
        )
        # Recompute global features from adjusted scores
        adj_probs  = [p for _, p in window_scores_adj]
        global_feat = [float(np.mean(adj_probs)), float(np.std(adj_probs))]
        pt_feats   = extract_recording_features(window_scores_adj, threshold=at, ...)

    # ── assemble 25-feature vector + LR (unchanged) ──────────────────────
    x = np.array(list(pt_feats.values()) + clin_list + global_feat).reshape(1, -1)
    x_scaled = self._scaler.transform(x)
    risk = float(self._lr.predict_proba(x_scaled)[0, 1])

    return BedState(
        ...
        god_mode_active = god_mode_active,
        active_events   = active_events,
    )
```

**ביצועים:**

| מצב | עלות נוספת |
|-----|-----------|
| לידה ללא god mode (`self._injector is None`) | **0** — אין בדיקה |
| לידה עם god mode, אין אירוע פעיל | **O(1)** — dict lookup בלבד |
| לידה עם god mode, אירוע פעיל | **O(k)** list scan, k ≤ 5 אירועים בד"כ |

---

### 10.7 שינויים ב-`BedState` ובסכמות ה-API

```python
# src/inference/pipeline.py — BedState מורחב

@dataclass
class BedState:
    ...  # כל השדות הקיימים — ללא שינוי

    # ── God Mode fields (optional, default off) ───────────────────────────
    god_mode_active: bool = False
    active_events:   list = field(default_factory=list)  # list[EventAnnotation]
```

```python
# api/models/schemas.py — BedUpdate מורחב

class EventAnnotationSchema(BaseModel):
    event_id:         str
    event_type:       str
    start_sample:     int
    end_sample:       int | None
    still_ongoing:    bool
    description:      str
    timeline_summary: str
    detected_details: dict

class BedUpdate(BaseModel):
    ...  # כל השדות הקיימים — ללא שינוי

    # God Mode:
    god_mode_active: bool = False
    active_events:   list[EventAnnotationSchema] = []
```

---

### 10.8 נקודות API חדשות

```
api/routers/god_mode.py
```

| Method | Path | תיאור | Body |
|--------|------|-------|------|
| POST | `/api/god-mode/inject` | הזרק אירוע — feature override + signal swap | `{bed_id, event_type, duration_seconds\|null, severity, description}` |
| DELETE | `/api/god-mode/events/{event_id}` | סיים אירוע + שחזור הקלטה | `?bed_id=bed_01` |
| GET | `/api/god-mode/events` | רשימת אירועים | `?bed_id=bed_01` |
| DELETE | `/api/god-mode/clear/{bed_id}` | נקה כל אירועי לידה + שחזור הקלטה | — |
| POST | `/api/god-mode/enable` | הפעל God Mode system-wide | — |
| GET | `/api/god-mode/status` | סטטוס + רשימת event types עם catalog | — |

> **הערה:** המימוש הסופי ב-`api/routers/god_mode.py` שונה מהדוגמה המקורית בסקשן זה — ראה `docs/god_mode_signal_plan.md §5` לקוד המדויק.

**תגובת inject:**
```json
{"event_id": "...", "status": "injected", "signal_swapped": true, "start_sample": 1234}
```
- `signal_swapped: true` — הקלטה הוחלפה להקלטה פתולוגית אמיתית
- `signal_swapped: false` — feature override בלבד (fallback אם אין קטלוג)

**תגובת end_event:**
```json
{"status": "ended", "recording_restored": true}
```

**תגובת status:**
```json
{
  "enabled": true,
  "signal_swap_available": true,
  "available_event_types": ["late_decelerations", "bradycardia", ...]
}
```

---

### 10.9 Frontend — God Mode Panel

**מיקום:** `frontend/src/components/god-mode/GodModePanel.tsx`  
**מופיע ב:** `DetailView` בלבד — לא ב-`WardView` (כדי לא לבלבל)

```
┌─── God Mode Control ──────────────────────────────────────────────┐
│  [Late Decels] [Variable] [Prolonged] [Sinusoidal] [Tachysystole] │
│  [Bradycardia] [Tachycardia] [Low Var] [⚡ COMBINED SEVERE]       │
│                                                                   │
│  עוצמה:   ○─────────●────○  0.85                                  │
│  משך: [ 10 min ▼ ]  ● Ongoing                                     │
│                          [→ הזרק אירוע]                           │
│                                                                   │
│  אירועים פעילים:                                                  │
│  ● LATE_DECELS   החל 00:12:34 | עדיין פעיל  [📡 Signal]  [✕ עצור]│
│  ✓ VARIABLE      החל 00:08:00 | משך 00:03:20                      │
└───────────────────────────────────────────────────────────────────┘
```

> **[📡 Signal]** — מוצג כשה-inject החזיר `signal_swapped: true`. מעיד שהגרף מציג הקלטה פתולוגית אמיתית.
> כפתורי EventType מסומנים ב-★ כשיש להם entries בקטלוג (`available_event_types` מ-`GET /status`).
> כפתורים ללא catalog entries (אם יש) מוצגים עם opacity נמוך + tooltip "feature override only".

#### סמני ציר הזמן על גרף ה-CTG

כשיש `active_events` ב-`BedUpdate`:
- **▼ (חץ למטה)** על ציר הזמן בנקודת ה-`start_sample` — "התחלת אירוע"
- **▲ (חץ למעלה)** על ציר הזמן בנקודת ה-`end_sample` — "סוף אירוע"
- **►** (מתמשך) — אם `still_ongoing`, קו שרוף מ-start עד הקצה הנוכחי של הגרף
- כל סמן עם tooltip: שם האירוע + ציר הזמן

#### Event Journal (טבלת אירועים מתחת לגרף)

| אירוע | התחלה | סיום | משך | זוהה | פרטים |
|-------|-------|------|-----|------|-------|
| Late Decels | 00:12:34 | עדיין פעיל | — | ✅ | 4 דיצלרציות, עומק 28 bpm |
| Variable | 00:08:00 | 00:11:20 | 3:20 | ✅ | 5 דיצלרציות, עומק 35 bpm |

---

### 10.10 הסבר מפורט — "מה זוהה בדיוק"

כשהמשתמש מרחף/לוחץ על אירוע, מוצג פאנל `DetectionDetail`:

```
┌─── פרטי זיהוי: Late Decelerations ────────────────────────────────┐
│                                                                   │
│  🕐 ציר זמן:   החל 00:12:34 | עדיין פעיל (04:22)                 │
│                                                                   │
│  📊 מה זוהה מבחינה קלינית:                                        │
│     • n_late_decelerations = 4  (רגיל: <1)                        │
│     • max_deceleration_depth = 28.0 bpm  (רגיל: <15)              │
│     • variability_category = Minimal (1/3)  — מדאיג               │
│                                                                   │
│  🤖 מה ה-AI ראה:                                                  │
│     • window_prob אחרון: 0.82  (סף: 0.50)                         │
│     • alert segments: 2 רצפים רציפים                               │
│     • total_alert_duration: 3.5 דקות                               │
│                                                                   │
│  ⚠️ ציון סיכון: 0.87  (סף להחלטה: 0.46) — ALERT                  │
│                                                                   │
│  📝 פרשנות:                                                       │
│     זיהוי דיצלרציות מאוחרות ריפלקטיביות לגירוי רחמי.             │
│     תתחיל עם תנוועה עוברית ואוקסיגנציה אמהית, הערך מחדש ב-15 דק.│
└───────────────────────────────────────────────────────────────────┘
```

---

### 10.11 החלפת הקלטה אמיתית (Signal Swap) — במקום סינתזה

> **שינוי מהתכנון המקורי:** הגישה של `signal_synthesizer.py` (סינתזת אות CTG מלאכותי) **בוטלה**.
> במקום זה, God Mode **מחליף את ההקלטה** שהמיטה מנגנת להקלטה אמיתית שמכילה פתולוגיה.
> ראה `docs/god_mode_signal_plan.md` לתכנון מלא.

**גישה דו-שכבתית:**
1. **שכבת Feature Override** — אפקט מיידי על risk score (תוך 6 שניות)
2. **שכבת Signal Swap** — החלפת ההקלטה להקלטה עם פתולוגיה אמיתית → הגרף מראה דפוס אמיתי

**מרכיבים:**
- `scripts/catalog_pathologies.py` — סריקה חד-פעמית של כל ההקלטות (552), מייצר `data/god_mode_catalog.json`
- `src/god_mode/segment_store.py` — טוען את הקטלוג, מספק בחירת הקלטה לפי סוג אירוע
- `generator/replay.py` → `ReplayEngine.swap_recording()` — מחליף הקלטה mid-stream
- `RecordingReplay.seek()` — מאפשר התחלה ממיקום ספציפי בהקלטה

**יתרונות על סינתזה:**
- נתונים אמיתיים 100% — רופא רואה CTG אמיתי
- PatchTST מזהה טבעית (אומן על אותם נתונים)
- מורכבות פיתוח נמוכה — swap recording + seek
- עקביות מלאה בין גרף לזיהוי

---

### 10.12 מבנה קבצים חדשים של God Mode

```
scripts/
└── catalog_pathologies.py    ← one-time build step → data/god_mode_catalog.json

data/
└── god_mode_catalog.json     ← 552 recordings × 9 event types (pre-built)

src/
└── god_mode/
    ├── __init__.py
    ├── types.py              ← InjectionEvent (+ original_recording_id, signal_swapped),
    │                            EventAnnotation, EventType
    ├── injector.py           ← GodModeInjector (singleton, thread-safe)
    │                            + get_event() + clear_bed() → list
    ├── overrides.py          ← build_feature_override() per EventType
    └── segment_store.py      ← SegmentStore (catalog loader + segment selection)

api/
└── routers/
    └── god_mode.py           ← FastAPI router: /api/god-mode/* (6 endpoints)

frontend/src/
└── components/
    └── god-mode/
        ├── GodModePanel.tsx      ← כפתורי הזרקה + אירועים פעילים
        ├── DetectionDetail.tsx   ← פאנל הסבר מפורט
        └── EventJournal.tsx      ← טבלת היסטוריית אירועים
```

---

### 10.13 סיכום — למה הגישה הזו נכונה

| דרישה | פתרון |
|-------|-------|
| **זיהוי מובטח תמיד** | Override ישיר של features → LR מקבל ערכים "מושלמים" → risk > threshold בוודאות |
| **נקודת התחלה וסיום** | `start_sample` + `end_sample` מתורגמים ל-HH:MM:SS; סמנים על גרף CTG |
| **"עדיין לא הסתיים"** | `end_sample = None` → `still_ongoing = True` → קו מתמשך על הגרף + badge "פעיל" |
| **הסבר מפורט** | `detected_details` מכיל ערכי features בפועל; `DetectionDetail` מסביר קלינית ו-AI |
| **ביצועים מהירים** | `has_active_events()` O(1); לידות רגילות אפס overhead; override O(k≤5) |
| **לא שובר architecture** | God Mode הוא שכבה נוספת, לא חלק מה-pipeline עצמו |
| **thread-safe** | `threading.Lock` מגן על `_events` dict; `push()` סינכרוני ו-thread-safe (`queue.put_nowait`) |

---

---

## 11. ניתוח פערים, תיקונים ושיפורים לייצור

**גרסה:** 2.0 | **תאריך ביקורת:** 2026-03-05

סקשן זה מתעד: (א) בעיות ופערים שנמצאו בתכנית המקורית, (ב) תיקונים שכבר בוצעו בשלבים 1–10, ו-(ג) פיצ'רים ושיפורים נוספים הנדרשים למוצר תעשייתי מוגמר.

---

### 11.1 — בעיות קריטיות שתוקנו (Bugs in the Plan)

#### BUG-1: סתירה בממשק `RecordingReplay.get_next_sample()`
**מיקום:** שלב 2, ממשק `RecordingReplay`  
**הבעיה:** הדוקסטרינג אמר `Returns (fhr_bpm, uc_mmhg)` אבל ה-`_load_recording` טוען נתונים מנורמלים [0,1].  
**סכנה:** מימוש שיסתמך על הדוקסטרינג ישלח bpm לתוך `on_new_sample()` שמצפה לערכים מנורמלים — PatchTST יקבל ערכים של 140 (≡ 22,400 bpm מנורמל) ויפיק זבל.  
**תיקון:** ✅ הדוקסטרינג עודכן בסקשן 3.

#### BUG-2: `PipelineManager` לא מקבל `broadcaster` בקונסטרוקטור
**מיקום:** שלב 3, `api/main.py` lifespan + `pipeline_manager.py`  
**הבעיה:** ב-lifespan, `broadcaster` נוצר *אחרי* `mgr`, אבל `mgr.on_sample()` קורא ל-`self._broadcaster.push()`. מי מגדיר `_broadcaster` ב-`PipelineManager`?  
**סכנה:** `AttributeError` ב-call הראשון של `on_sample()` — קריסה שקטה בלי הסבר ברור.  
**תיקון:** ✅ סדר ה-lifespan תוקן (broadcaster נוצר ראשון), ו-`PipelineManager.__init__` קיבל `broadcaster` כפרמטר מחויב. ראה סקשנים 3 ו-4.

#### BUG-3: `current_sample_count` לא מוגדר כ-property
**מיקום:** סקשן 10 (God Mode router) — קוראים ל-`pipeline.current_sample_count`  
**הבעיה:** ב-`SentinelRealtime` לא הוגדרה property זו. ה-`_sample_count` הוא attribute פרטי.  
**תיקון:** ✅ יש להוסיף:
```python
# src/inference/pipeline.py — בתוך SentinelRealtime
@property
def current_sample_count(self) -> int:
    """Current number of samples processed. Used by God Mode for timestamp anchoring."""
    return self._sample_count
```

#### BUG-4: God Mode — לא מוגדר כיצד PipelineManager יוצר beds עם god_mode
**מיקום:** סקשן 10, שילוב ב-`SentinelRealtime`  
**הבעיה:** `SentinelRealtime.__init__` מקבל `god_mode: bool = False` אבל `PipelineManager.set_beds()` לא מגדיר מתי להעביר `god_mode=True`.  
**תיקון:** ✅ God Mode הוא **system-wide toggle**, לא per-bed. `PipelineManager.enable_god_mode()` מגדיר `_god_mode_enabled = True` ומחדיר `GodModeInjector` לכל ה-pipelines הקיימים והחדשים. ראה תיקון ב-`PipelineManager` בסקשן 4.

#### BUG-5: Race condition ב-reset() של SentinelRealtime
**מיקום:** שלב 1, `reset()`  
**הבעיה:** `reset()` מנקה `_fhr_ring`, `_uc_ring`, `_window_scores` ומאפס `_sample_count`. אם נקרא ב-thread אחד בזמן ש-`_compute_full_state()` רץ ב-thread אחר (ThreadPoolExecutor), ייתכן שתתקבל `BedState` עם `window_scores` חלקיים.  
**תיקון:** יש להוסיף `threading.Lock` ל-`SentinelRealtime`:
```python
# src/inference/pipeline.py
def __init__(self, ...):
    ...
    self._state_lock = threading.Lock()   # guards ring buffers + window_scores + sample_count

def on_new_sample(self, fhr_norm, uc_norm):
    with self._state_lock:
        self._fhr_ring.append(fhr_norm)
        self._uc_ring.append(uc_norm)
        self._sample_count += 1
        if self._sample_count % 24 == 0 and len(self._fhr_ring) >= 1800:
            return self._compute_full_state()   # still under lock
    return None

def reset(self):
    with self._state_lock:
        self._fhr_ring.clear()
        self._uc_ring.clear()
        self._window_scores.clear()
        self._sample_count = 0
```
> **הערה ביצועים:** `_compute_full_state()` רץ כל 6 שניות, ו-`on_new_sample()` רץ ב-4Hz. ה-lock נחזק לשברירי שנייה בלבד — אין risk של blocking.

#### BUG-6: אין fallback כשכל 5 מודלי PatchTST נכשלים
**מיקום:** שלב 1, `_run_ensemble()`  
**הבעיה:** אם `torch.no_grad()` קורס (OOM, CUDA error, corrupt weight), `_run_ensemble` זורק exception ולא מחזיר ערך. `on_new_sample` לא מגן על זה.  
**תיקון:**
```python
def _run_ensemble(self, signal: np.ndarray) -> float | None:
    try:
        x = torch.tensor(signal, dtype=torch.float32).unsqueeze(0)
        with torch.no_grad():
            probs = [torch.softmax(m(x), dim=-1)[0, 1].item() for m in self._models]
        return float(np.mean(probs))
    except Exception as exc:
        logger.error(f"[{self._bed_id}] PatchTST ensemble failed: {exc}")
        return None  # caller should skip this window_score entry
```
אם `_run_ensemble` מחזיר `None` — לא מוסיפים ל-`_window_scores`, מחזירים `None` מ-`on_new_sample`.

#### BUG-7: אובדן נתונים ב-CTG graph — `[-16:]` במקום `[-24:]`
**מיקום:** שלב 1, `_compute_full_state()` + סכמות `BedState`/`BedUpdate`  
**הבעיה:** `fhr_latest = list(fhr_arr)[-16:]` שולח 16 ערכים בכל tick, אבל stride=24. ה-frontend מצפה ל-24 ערכים חדשים כדי לצייר ללא פערים — 8 נקודות נשמטות בשקט כל 6 שניות, ובסביבת 16 לידות זה 128 נקודות חסרות בדקה → שרטוט CTG שבור.  
**תיקון:** ✅ `[-16:]` → `[-24:]` ב-`_compute_full_state`, ו-4 הערות הסכמה עודכנו ל-"last 24 samples — 1 full stride". ראה סקשנים 1 ו-4.

#### BUG-8: חסימת event loop — `on_new_sample` רץ synchronously בלולאת asyncio
**מיקום:** שלב 3, `ReplayEngine.run()` + שלב 4, `PipelineManager.on_sample`  
**הבעיה:** `ReplayEngine.run()` אסינכרוני, אבל `on_sample` קרא ל-`pipeline.on_new_sample()` ישירות מהלולאה. כל 6 שניות, `_run_ensemble` (~50ms) + `_compute_full_state` רצו על ה-event loop thread → כל ה-WebSockets נחסמו ל-800ms (עם 16 לידות × 50ms = 800ms חסימה).  
**תיקון:** ✅ `on_sample` עכשיו קורא `self._executor.submit(self._process_and_broadcast, ...)` ומחזיר מיידית. `_process_and_broadcast` רץ ב-ThreadPoolExecutor וקורא `self._broadcaster.push(state)` ישירות — `push()` סינכרוני ו-thread-safe (`queue.put_nowait`), לכן **אין צורך ב-`run_coroutine_threadsafe`**. ראה סקשנים 4 ו-9.

#### BUG-9: God Mode — תנאי window שגוי, אירוע בלתי נראה 7.5 דקות
**מיקום:** סקשן 10, `GodModeInjector.compute_override()`, לולאת `window_scores`  
**הבעיה:** `(s, max(p, min_prob)) if s >= event.start_sample` — `s` הוא *תחילת* החלון. אם אירוע הוזרק בסמפל 5000, חלון 3200–5000 מקבל `s=3200`, ו-`3200 >= 5000 = False` — החלון לא מקבל boost. God Mode ייכנס לפעולה רק 7.5 דקות מאוחר יותר, כשחלונות חדשים יתחילו ב-≥5000.  
**תיקון:** ✅ `s >= event.start_sample` → `s + 1800 >= event.start_sample` — בודק אם *סוף* החלון מגיע לאירוע. ראה סקשן 10.

#### BUG-10: React / lightweight-charts — כפילות קריאות `series.update()`
**מיקום:** סקשן 5, `useBedStream.ts` + `useCTGChart.ts`  
**הבעיה:** הדפוס המקורי: WebSocket → Zustand store update → component re-render → `appendSamples` נקרא ב-effect. ב-React Strict Mode (double-invoke) או כש-re-render לא קשור מפעיל את ה-effect, `series.update()` קורא עם אותם נתונים פעמיים → zigzag בגרף ו/או crash ב-lightweight-charts.  
**תיקון:** ✅ הוכנס `ChartUpdateBus` (pub/sub singleton). `useBedStream.onmessage` קורא (1) `updateFromWebSocket()` ל-Zustand (state ל-ward view), ו-(2) `chartUpdateBus.publish()` ישירות ל-chart hook — עוקף לחלוטין את מחזור ה-render של React. `useCTGChart` עושה subscribe ל-bus ב-`useEffect` וקורא `series.update()` ישירות. ראה סקשן 5 + `utils/chartUpdateBus.ts`.

#### BUG-11: God Mode — שרשור original_recording_id נשבר באירועים חופפים
**מיקום:** `api/routers/god_mode.py` (inject_event, end_event, clear_bed) + `api/services/pipeline_manager.py`
**הבעיה:** כשמזריקים שני אירועי God Mode על אותה מיטה ברצף, `inject_event` שומר את ה-`original_recording_id` מערך ההחזרה של `swap_recording()` — שזו ההקלטה הפתולוגית של האירוע הקודם, לא ההקלטה המקורית האמיתית. בסיום אירוע, המיטה משוחזרת להקלטה פתולוגית במקום לבסיס.
**תיקון:** ✅ הוספת `_baseline_recordings: dict[str, str]` ב-PipelineManager — שדה שזוכר את ההקלטה המקורית של כל bed (נקבע ב-`set_beds()`). `inject_event` משתמש ב-`manager.get_baseline_recording()` במקום בערך ההחזרה של `swap_recording()`. `end_event` בודק שאין אירועים חופפים פעילים לפני שחזור. `clear_bed` משחזר ישירות ל-baseline.

#### Design Caveats — God Mode (לא באגים, אלא מגבלות עיצוב מתועדות)
ראה תיעוד מלא ב-`docs/god_mode_signal_plan.md` סקשן "הסתייגויות עיצוב ידועות":
1. **Feature Mixing** — כש-signal swap + feature override פעילים במקביל, וקטור הפיצ'רים היברידי. בסדר כי override דוחף באותו כיוון כמו האות, ו-max() הופך אותו ל-no-op ברגע שהאות חזק מספיק.
2. **Transition Windows** — חלון ראשון אחרי swap מכיל תמהיל ישן/חדש. בסדר כי ring buffer ארוך (30 דקות) ו-override ממסך רעש.
3. **Demo Bias** — הדגמות נקיות יותר מנתונים קליניים אמיתיים. מוקל ע"י שימוש בהקלטות אמיתיות (לא סינתטיות).

---

### 11.2 — API חסרות: `GET /api/recordings` ו-state ראשוני

#### `GET /api/recordings` — רשימת הקלטות זמינות
**בעיה:** הפרונטאנד מאפשר שינוי recording לכל לידה, אבל אין endpoint שמחזיר את הרשימה הזמינה. המשתמש לא יכול לבחור recording_id בלי לדעת מה קיים.

```python
# api/routers/recordings.py

@router.get("/api/recordings")
async def list_recordings() -> list[RecordingInfo]:
    """
    Lists all .npy files in data/recordings/.
    Returns recording_id, file size, and duration in seconds.
    """
    recordings_dir = Path("data/recordings")
    result = []
    for path in sorted(recordings_dir.glob("*.npy")):
        try:
            data = np.load(path, mmap_mode='r')   # memory-mapped, no full load
            duration_s = data.shape[1] / 4.0
            result.append(RecordingInfo(
                recording_id = path.stem,
                duration_seconds = duration_s,
                file_size_kb = path.stat().st_size // 1024,
            ))
        except Exception:
            continue
    return result

class RecordingInfo(BaseModel):
    recording_id:     str
    duration_seconds: float
    file_size_kb:     int
```

#### Initial State ב-WebSocket Connect
**בעיה:** לקוח שמתחבר ל-`/ws/stream` לא מקבל כלום עד ה-tick הבא (עד 6 שניות).  
ה-UI יציג ריק למשך 6 שניות — חוויה גרועה ומבלבלת.

**תיקון — ב-`api/routers/websocket.py`:**
```python
@router.websocket("/ws/stream")
async def ws_stream(websocket: WebSocket, request: Request):
    mgr: PipelineManager = request.app.state.manager
    broadcaster: AsyncBroadcaster = request.app.state.broadcaster

    await websocket.accept()
    client_id = await broadcaster.register(websocket)

    try:
        # ── שלח state ראשוני מיידי ─────────────────────────────────────────
        current_states = mgr.get_bed_states()
        if current_states:
            await websocket.send_json({
                "type": "initial_state",
                "timestamp": time.time(),
                "beds": [dataclasses.asdict(s) for s in current_states],
            })

        # ── המתן להודעות (ping / close) ───────────────────────────────────
        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        await broadcaster.unregister(client_id)
```

Frontend מטפל ב-`type: "initial_state"` בנפרד מ-`batch_update`:
```typescript
ws.onmessage = (event) => {
  const msg = JSON.parse(event.data)
  if (msg.type === 'initial_state') {
    useBedStore.getState().initializeFromSnapshot(msg.beds)
  } else if (msg.type === 'batch_update') {
    for (const update of msg.updates) {
      useBedStore.getState().updateFromWebSocket(update)
    }
  }
}
```

---

### 11.3 — Server-Side Alert History & Audit Log

**בעיה:** הגרף `Alert History` ב-`DetailView` הוגדר בממשק אבל לא מוגדרת שכבת נתונים מתאימה. אם המשתמש מרענן את הדף, כל ההיסטוריה נמחקת (כיוון שהיא נשמרת רק ב-frontend ring buffers).

#### `AlertHistoryStore` — backend in-memory
```python
# api/services/alert_history.py

from collections import deque
from dataclasses import dataclass
import time

@dataclass
class AlertEvent:
    bed_id:      str
    timestamp:   float
    risk_score:  float
    alert_on:    bool       # True = alert started, False = alert cleared
    elapsed_s:   float      # recording position at event time

class AlertHistoryStore:
    """
    In-memory rolling store: last 200 alert events per bed.
    Persisted to data/alert_log.jsonl on each write (append-only).
    On startup, loads existing log to restore history after restart.
    """
    MAX_PER_BED = 200

    def __init__(self, log_path: Path = Path("data/alert_log.jsonl")):
        self._log_path = log_path
        self._store: dict[str, deque[AlertEvent]] = {}
        self._last_alert_state: dict[str, bool] = {}
        self._load_from_file()

    def record(self, state: "BedState") -> None:
        """Called from PipelineManager on every BedState emission."""
        bed_id = state.bed_id
        prev   = self._last_alert_state.get(bed_id, False)

        # Log only on state *transitions*, not every tick
        if state.alert != prev:
            self._last_alert_state[bed_id] = state.alert
            event = AlertEvent(
                bed_id     = bed_id,
                timestamp  = state.timestamp,
                risk_score = state.risk_score,
                alert_on   = state.alert,
                elapsed_s  = state.elapsed_seconds,
            )
            self._store.setdefault(bed_id, deque(maxlen=self.MAX_PER_BED)).append(event)
            self._append_to_file(event)

    def get_history(self, bed_id: str, last_n: int = 50) -> list[AlertEvent]:
        return list(self._store.get(bed_id, []))[-last_n:]

    def _append_to_file(self, event: AlertEvent):
        try:
            with open(self._log_path, 'a') as f:
                f.write(json.dumps(dataclasses.asdict(event)) + "\n")
        except OSError:
            pass   # non-critical — log failure doesn't break monitoring
```

**שילוב ב-`PipelineManager`:**
```python
# api/services/pipeline_manager.py
def on_sample(self, bed_id: str, fhr_norm: float, uc_norm: float) -> None:
    pipeline = self._pipelines.get(bed_id)
    if pipeline:
        state = pipeline.on_new_sample(fhr_norm, uc_norm)
        if state:
            self._alert_history.record(state)   # ← חדש
            self._broadcaster.push(state)
```

**Endpoint:**
```
GET /api/beds/{bed_id}/alerts?last_n=50
→ list[AlertEvent]
```

---

### 11.4 — Stale Data Watchdog

**בעיה:** אם ה-`ReplayEngine` נתקע (exception, event loop blockage), ה-UI מציג נתונים ישנים בלי כל אינדיקציה. ב-ward monitoring זה מסוכן.

#### Backend: `last_update_ts` בכל BedState
`BedState.timestamp` כבר קיים — נוסיף `server_time` נפרד להשוואה:
```python
# BedState — שדה נוסף
last_update_server_ts: float = field(default_factory=time.time)
```

#### Frontend: Stale indicator
```typescript
// hooks/useStaleDetector.ts
export function useStaleDetector(bedId: string, thresholdSec = 15) {
  const lastUpdate = useBedStore(s => s.beds.get(bedId)?.lastUpdate ?? 0)
  const [isStale, setIsStale] = useState(false)

  useEffect(() => {
    const interval = setInterval(() => {
      setIsStale(Date.now() / 1000 - lastUpdate > thresholdSec)
    }, 2000)
    return () => clearInterval(interval)
  }, [lastUpdate, thresholdSec])

  return isStale
}
```

**UI:** כרטיס לידה עם stale > 15s מציג badge `⏸ STALE` ועמעום (opacity: 0.6).  
כל המסך עם stale > 30s מציג `⚠ CONNECTION LOST` banner.

#### Backend: Heartbeat ping
```python
# api/services/broadcaster.py
async def _heartbeat_loop(self) -> None:
    """Sends {"type": "heartbeat", "ts": ...} every 5 sec to all clients."""
    while self._running:
        await asyncio.sleep(5)
        await self._send_to_all({"type": "heartbeat", "ts": time.time()})
```

---

### 11.5 — Simulation Speed Control

**בעיה:** אין אפשרות להאיץ את הסימולציה לדמו. הקלטה של 60 דקות דורשת 60 דקות אמיתיות — לא מעשי.

**שינוי ב-`ReplayEngine`:**
```python
# generator/replay.py — ReplayEngine

class ReplayEngine:
    def __init__(self, ..., speed: float = 1.0):
        self._speed = speed   # 1.0 = realtime, 2.0 = 2x, 10.0 = 10x

    def set_speed(self, speed: float) -> None:
        """Thread-safe speed change. Effective on next tick.
        Supported range: [1.0, 20.0]. Slow-motion (<1x) is NOT supported
        — the tick loop fires 1 sample/0.25s minimum; further slow-down
        would require accumulator logic beyond current scope.
        UI exposes: 1×, 2×, 5×, 10×.
        """
        assert 1.0 <= speed <= 20.0, "Speed must be in [1.0, 20.0]"
        self._speed = speed

    async def run(self) -> None:
        while self._running:
            t_start = asyncio.get_event_loop().time()
            ticks_this_cycle = max(1, round(self._speed))

            for _ in range(ticks_this_cycle):
                if not self._running: break
                for bed_id, replay in list(self._beds.items()):
                    fhr, uc = replay.get_next_sample()
                    self._callback(bed_id, fhr, uc)

            elapsed = asyncio.get_event_loop().time() - t_start
            sleep_time = max(0.0, 0.25 - elapsed)
            await asyncio.sleep(sleep_time)
```

> **הסבר:** במקום לשנות את מרווח ה-sleep, אנו מריצים `ticks_this_cycle` ticks בכל 0.25s. ב-2x — 2 samples per 0.25s ≡ 8Hz effective. ב-10x — 10 samples → PatchTST מקבל 120 samples/sec אבל window עדיין 1800 samples; נקודת ה-inference גם היא מגיעה 10x מהר.

**Endpoints:**
```
POST /api/simulation/speed   body: {"speed": 2.0}
GET  /api/simulation/status  → מחזיר גם speed_factor
```

**UI — Speed toggle:**
```
[1×]  [2×]  [5×]  [10×]
```
> **הגבלה:** ב-speed > 4x, frontend מציג CTG timeline עם skip — לא כל sample מוצג, רק כל N-th.

---

### 11.6 — אבטחת God Mode

**בעיה:** ה-endpoints `/api/god-mode/*` פתוחים לחלוטין. בהצגה ב-ward, עמית לא מורשה יכול לבצע הזרקה שתיצור false alerts.

**פתרון: PIN-based middleware (פשוט, לא מצריך auth framework מלא)**
```python
# api/middleware/god_mode_guard.py

GOD_MODE_PIN_HEADER = "X-God-Mode-Pin"

class GodModeGuard(BaseHTTPMiddleware):
    def __init__(self, app, pin: str):
        super().__init__(app)
        self._pin_hash = hashlib.sha256(pin.encode()).hexdigest()

    async def dispatch(self, request: Request, call_next):
        if request.url.path.startswith("/api/god-mode"):
            provided = request.headers.get(GOD_MODE_PIN_HEADER, "")
            if hashlib.sha256(provided.encode()).hexdigest() != self._pin_hash:
                return JSONResponse({"detail": "Unauthorized"}, status_code=403)
        return await call_next(request)
```

**הגדרה ב-`api/config.py`:**
```python
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    god_mode_pin: str = "1234"   # override with env var: GOD_MODE_PIN=xxxx
    god_mode_enabled: bool = False  # default off; enable with GOD_MODE_ENABLED=true
    model_config = SettingsConfig(env_file=".env")
```

Frontend שומר PIN ב-`sessionStorage` (לא localStorage — נמחק בסגירת tab):
```typescript
// stores/uiStore.ts
godModePin: string | null     // set after successful PIN entry
godModeUnlocked: boolean      // True when PIN was accepted (UI-side only)
```

---

### 11.7 — מערכת Logging מרכזית

**בעיה:** אין logging מוגדר בשום מקום. קריסה, alert, שגיאת inference — הכל אבד.

```python
# api/logging_config.py

import logging
import logging.handlers
from pathlib import Path

def setup_logging(log_dir: Path = Path("logs")) -> None:
    log_dir.mkdir(exist_ok=True)

    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)-30s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Rotating file: 10MB × 5 files
    fh = logging.handlers.RotatingFileHandler(
        log_dir / "sentinel.log", maxBytes=10*1024*1024, backupCount=5
    )
    fh.setFormatter(fmt)

    # Console (dev only)
    ch = logging.StreamHandler()
    ch.setFormatter(fmt)

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(fh)
    root.addHandler(ch)

    # Special audit logger — append-only for God Mode & Alerts
    audit = logging.getLogger("sentinel.audit")
    ah = logging.FileHandler(log_dir / "audit.log")
    ah.setFormatter(fmt)
    audit.addHandler(ah)
    audit.propagate = False
```

**מה נלכד ב-audit.log:**
- כל alert_on / alert_off transition (עם bed_id, risk_score, recording_id, elapsed_s)
- כל god mode inject / end / clear (עם bed_id, event_type, user_ip)
- כל שינוי configuration (bed add/remove, speed change)
- startup וביצועי load (model load time, startup time)

---

### 11.8 — Loading State ו-Startup Screen

**בעיה:** טעינת 5 מודלי PatchTST + scaler/LR לוקחת 3–8 שניות. ה-frontend יציג blank screen או שגיאת WebSocket בלי הסבר.

#### Backend: SSE endpoint לסטטוס startup
```python
# api/routers/system.py

@router.get("/api/system/startup-status")
async def startup_status(request: Request):
    """Server-Sent Events stream for startup progress."""
    async def event_stream():
        # שולח events כל שלב
        for event in request.app.state.startup_events:
            yield f"data: {json.dumps(event)}\n\n"
        yield f"data: {json.dumps({'status': 'ready'})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")
```

#### Frontend: Splash screen
```
┌────────────────────────────────────────┐
│                                        │
│        SentinelFetal2                  │
│                                        │
│  ▓▓▓▓▓▓▓▓▓▓▓▓░░░░░░░░   62%           │
│                                        │
│  Loading PatchTST fold 4/5...          │
│                                        │
└────────────────────────────────────────┘
```

---

### 11.9 — Simulation Recording Browser UI

**בעיה:** אין UI לשינוי הקלטה per bed. המשתמש לא יכול לבחור recording_id בלי לדעת מה קיים.

#### Modal: Recording Assignment
```
┌─── שנה הקלטה — bed_01 ────────────────────────┐
│                                               │
│  חיפוש: [____________________]               │
│                                               │
│  ID     משך       גודל   ◻ נוכחי            │
│  1001   45:32    112 KB  ○                   │
│  1023   62:10    148 KB  ● ← נוכחי           │
│  1045   38:55     95 KB  ○                   │
│  ...                                         │
│                                               │
│          [ביטול]  [✓ שנה הקלטה]              │
└───────────────────────────────────────────────┘
```

---

### 11.10 — Sound Alerts

**בעיה:** ב-ward monitoring, המיילדת לא תמיד מסתכלת על המסך. אין אינדיקציה קולית לalert חדש.

**שימוש ב-Web Audio API (ללא dependency חיצוני):**
```typescript
// utils/alertSound.ts

let audioCtx: AudioContext | null = null

function getAudioCtx(): AudioContext {
  if (!audioCtx) audioCtx = new AudioContext()
  return audioCtx
}

export function playAlertTone(escalate = false): void {
  const ctx = getAudioCtx()
  const osc = ctx.createOscillator()
  const gain = ctx.createGain()

  osc.connect(gain)
  gain.connect(ctx.destination)

  // Two-tone alert: 880Hz → 1100Hz (clinical, non-alarming)
  osc.frequency.setValueAtTime(880, ctx.currentTime)
  osc.frequency.setValueAtTime(1100, ctx.currentTime + 0.15)

  gain.gain.setValueAtTime(0.3, ctx.currentTime)
  gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.5)

  osc.start(ctx.currentTime)
  osc.stop(ctx.currentTime + 0.5)
}
```

**כללי הפעלה:**
- Alert חדש (transition `false → true`): נגן טון פעם אחת
- Alert ממשיך > 2 דקות: נגן חזרה
- Alert נמחק: ללא צליל
- UI: כפתור `🔔 / 🔕` מהיר להשתקה

---

### 11.11 — Export & Report Generation

**בעיה:** ב-demo/clinical setting, צריך להוציא דו"ח של מה שקרה. אין export כיום.

#### Backend endpoint:
```
GET /api/beds/{bed_id}/export?format=json|csv
```
מחזיר:
```json
{
  "bed_id": "bed_01",
  "recording_id": "1023",
  "export_ts": "2026-03-05T14:32:00Z",
  "alert_events": [...],
  "god_mode_events": [...],
  "final_risk_score": 0.72,
  "clinical_summary": {
    "n_late_decelerations": 2,
    "max_deceleration_depth_bpm": 28.0,
    ...
  }
}
```

#### Frontend: Print View
כפתור `⬇ Export` ב-`DetailView` → פותח print view (`window.print()`) עם:
- header: bed_id, recording_id, תאריך/שעה
- CTG trace (screenshot מה-lightweight-chart canvas)
- Risk timeline
- Clinical Findings summary
- Alert History

---

### 11.12 — Bed Notes

**בעיה:** אין דרך לרשום הערה ("בדיקה פיזית בוצעת", "אוקסיגן ניתן") על לידה ספציפית.

```python
# api/routers/beds.py — endpoint נוסף

class NoteRequest(BaseModel):
    text: str = Field(max_length=500)

@router.post("/api/beds/{bed_id}/notes")
async def add_note(bed_id: str, req: NoteRequest):
    ts = time.time()
    note = BedNote(bed_id=bed_id, text=req.text, created_at=ts)
    note_store.add(note)
    # audit log
    logging.getLogger("sentinel.audit").info(
        f"NOTE | bed={bed_id} | text={req.text[:80]}"
    )
    return note
```

**UI — Notes Panel ב-DetailView:**
```
┌─── הערות ──────────────────────────────────────┐
│  14:32 — בדיקת US בוצעה, עובר תקין             │
│  14:28 — אוקסיגן 6L/min ניתן לאם              │
│                                                │
│  [+ הוסף הערה________________]  [שמור]        │
└────────────────────────────────────────────────┘
```

---

### 11.13 — Full-Screen / Kiosk Mode

```typescript
// hooks/useFullscreen.ts
export function useFullscreen() {
  const toggle = useCallback(() => {
    if (!document.fullscreenElement) {
      document.documentElement.requestFullscreen()
    } else {
      document.exitFullscreen()
    }
  }, [])
  return { toggle }
}
```

**UI:** כפתור `⛶` בheader → Full screen WardView. במצב kiosk, כرटيس alerts עם border עבה + auto-scroll לכרטיס הבעייתי.

---

### 11.14 — Deployment: Docker + Startup Check

#### `Dockerfile`
```dockerfile
FROM python:3.12-slim AS backend

WORKDIR /app
RUN pip install --no-cache-dir uv
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY . .

# ── Startup validation ──────────────────────────
RUN uv run --frozen python scripts/validate_artifacts.py   # fails build if weights/scaler/lr missing

EXPOSE 8000
CMD ["uv", "run", "--frozen", "uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000", \
     "--workers", "1", "--log-level", "info"]
```

#### `scripts/validate_artifacts.py` — startup check script
```python
"""
Run at container BUILD TIME to validate static ML artifacts
(weights, scaler, LR, config). Data recordings are checked
at RUNTIME in the FastAPI lifespan, NOT here, because the
data volume is only available after docker-compose start.
Exits with code 1 if any check fails.
"""
import sys, json, pickle, torch
from pathlib import Path

errors = []

# 1. production_config.json
cfg = None
try:
    cfg = json.load(open("artifacts/production_config.json"))
except Exception as e:
    errors.append(f"production_config.json failed: {e}")

# 2. weights files (only if config loaded successfully)
if cfg is not None:
    for fold in range(cfg.get("n_folds", 5)):
        p = Path(cfg["weights"][fold])
        if not p.exists():
            errors.append(f"Missing weight: {p}")
        else:
            try:
                torch.load(p, map_location="cpu", weights_only=True)
            except Exception as e:
                errors.append(f"Weight corrupt {p}: {e}")
else:
    errors.append("Skipping weight checks — config not loaded")

# 3. scaler + lr
for name in ("production_scaler.pkl", "production_lr.pkl"):
    try:
        pickle.load(open(f"artifacts/{name}", "rb"))
    except Exception as e:
        errors.append(f"{name} failed: {e}")

# ⚠ data/recordings/ is NOT checked here — it is volume-mounted at runtime.
# Add this check in the FastAPI lifespan (startup event) instead.

if errors:
    print("ARTIFACT VALIDATION FAILED:")
    for e in errors: print(f"  ✗ {e}")
    sys.exit(1)

n_folds = cfg.get('n_folds', 5) if cfg else '?'
print(f"✓ All artifacts validated ({n_folds} folds)")
```

> **Runtime data check** — add the following to `api/main.py` lifespan (after volume mount is available):
> ```python
> # lifespan startup: verify recordings directory
> recordings_dir = Path("data/recordings")
> if not recordings_dir.exists() or not any(recordings_dir.glob("*.npy")):
>     logger.critical("No .npy files in data/recordings/ — is the data volume mounted?")
>     raise RuntimeError("Missing recording data")
> ```

#### `docker-compose.yml`
```yaml
version: "3.9"

services:
  backend:
    build: .
    ports:
      - "8000:8000"
    volumes:
      - ./data:/app/data          # recordings + alert log
      - ./weights:/app/weights    # model weights (read-only in prod)
      - ./logs:/app/logs          # log files
    environment:
      - GOD_MODE_PIN=change_me    # override in production
      - GOD_MODE_ENABLED=false
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/api/health"]
      interval: 30s
      timeout: 5s
      retries: 3

  frontend:
    build:
      context: ./frontend
      dockerfile: Dockerfile.frontend   # multi-stage: build → nginx
    ports:
      - "80:80"
    depends_on:
      - backend
```

`frontend/Dockerfile.frontend`:
```dockerfile
# Stage 1: build
FROM node:20-slim AS build
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build   # outputs to /app/dist

# Stage 2: serve
FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
```

`frontend/nginx.conf`:
```nginx
server {
    listen 80;
    root /usr/share/nginx/html;
    index index.html;
    # SPA: return index.html for all routes
    location / { try_files $uri $uri/ /index.html; }
    # Proxy WebSocket and API to backend
    location /api/ { proxy_pass http://backend:8000; }
    location /ws/  {
        proxy_pass http://backend:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "Upgrade";
    }
}
```

---

### 11.15 — פיצ'ר: Risk Trend Indicator

**בעיה:** ה-`BedCard` מציג risk_score נוכחי אבל לא את הכיוון — האם הסיכון עולה או יורד?

**שדה חדש ב-`BedState`:**
```python
risk_delta: float = 0.0   # risk_score[-1] - risk_score[-4] (אחת לדקה, 10 נקודות אחורה)
```

**UI:**
```
Risk  ███████░░░░  0.72  ↑ +0.08   ⚠
```
- `↑` **bold** (`font-bold text-gray-900`) = עולה
- `↓` muted (`text-gray-400`) = יורד
- `→` regular = יציב

> **ביאור צבעי:** עונה אותו B&W — אין אדום/ירוק. הכיוון מועבר בטןחות גופן (`font-bold` vs muted) ו-`text-gray-900`/`text-gray-400` — שנייהם צבעי גווני קיימים בפלטת ה-B&W.

---

### 11.16 — סיכום: Backend API מלא (Revised)

| Method | Path | תיאור | חדש? |
|--------|------|-------|------|
| GET | `/api/health` | בריאות שרת | קיים |
| GET | `/api/system/startup-status` | SSE stream של טעינה | ✨ חדש |
| GET | `/api/simulation/status` | מצב סימולציה + speed | משופר |
| POST | `/api/simulation/start` | הפעל | קיים |
| POST | `/api/simulation/stop` | עצור | קיים |
| POST | `/api/simulation/pause` | השהה | קיים |
| POST | `/api/simulation/resume` | חדש | קיים |
| POST | `/api/simulation/speed` | שנה מהירות | ✨ חדש |
| GET | `/api/recordings` | רשימת הקלטות זמינות | ✨ חדש |
| GET | `/api/beds` | כל הלידות | קיים |
| GET | `/api/beds/{id}` | snapshot לידה | קיים |
| GET | `/api/beds/{id}/history` | היסטוריית FHR/UC | קיים |
| GET | `/api/beds/{id}/alerts` | היסטוריית alerts | ✨ חדש |
| POST | `/api/beds/{id}/notes` | הוסף הערה | ✨ חדש |
| GET | `/api/beds/{id}/export` | export JSON/CSV | ✨ חדש |
| POST | `/api/beds/config` | שנה configuration | קיים |
| POST | `/api/god-mode/inject` | הזרק אירוע | קיים |
| DELETE | `/api/god-mode/events/{id}` | סיים אירוע | קיים |
| GET | `/api/god-mode/events` | רשימת אירועים | קיים |
| DELETE | `/api/god-mode/clear/{bed}` | נקה לידה | קיים |
| WS | `/ws/stream` | Real-time stream | משופר |

---

### 11.17 — מבנה קבצים מעודכן (Diff מסקשן 7)

```diff
  src/
+ └── god_mode/               ← חדש (סקשן 10)
+     ├── __init__.py
+     ├── types.py
+     ├── injector.py
+     ├── overrides.py
+     └── segment_store.py

  api/
  ├── ...
  ├── routers/
  │   ├── simulation.py
  │   ├── beds.py
  │   ├── websocket.py        ← משופר: initial_state message
+ │   ├── recordings.py       ← חדש: GET /api/recordings
+ │   ├── system.py           ← חדש: startup-status SSE
  │   └── god_mode.py
  └── services/
+     ├── alert_history.py    ← חדש: AlertHistoryStore
+     ├── note_store.py       ← חדש: BedNote
      ├── pipeline_manager.py ← משופר: broadcaster param, god_mode toggle
      ├── broadcaster.py      ← משופר: heartbeat loop
      └── model_loader.py

+ api/middleware/
+  └── god_mode_guard.py      ← חדש: PIN auth middleware

  frontend/src/
  ├── ...
  ├── components/
  │   ├── ...
  │   ├── god-mode/
+ │   ├── notes/              ← חדש: NotesPanel.tsx
+ │   └── export/             ← חדש: ExportButton.tsx, PrintView.tsx
+ ├── hooks/
+ │   ├── useStaleDetector.ts ← חדש
+ │   └── useFullscreen.ts    ← חדש
+ └── utils/
+     └── alertSound.ts       ← חדש: Web Audio API

+ scripts/
+   └── validate_artifacts.py ← חדש: startup check

+ logs/                       ← חדש: sentinel.log, audit.log (gitignored)
+ data/alert_log.jsonl        ← חדש: append-only alert audit (gitignored)
+ Dockerfile
+ docker-compose.yml
+ .env.example
```

---

### 11.18 — סיכום ממשיות: מה עוצר אותנו עכשיו

| סדר | פריט | זמן משוער | תלויות |
|-----|------|-----------|--------|
| P0 | BUG-5: Lock ב-SentinelRealtime | קצר | pipeline.py |
| P0 | BUG-6: Fallback ב-_run_ensemble | קצר | pipeline.py |
| P0 | `current_sample_count` property | קצר | pipeline.py |
| P1 | `GET /api/recordings` | קצר | recordings.py |
| P1 | Initial state ב-WS connect | קצר | websocket.py |
| P1 | `AlertHistoryStore` | בינוני | alert_history.py |
| P1 | `validate_artifacts.py` | קצר | scripts/ |
| P2 | Stale data watchdog | בינוני | broadcaster + frontend |
| P2 | Simulation speed control | בינוני | replay.py + API |
| P2 | Logging | קצר | logging_config.py |
| P2 | CORS + Vite proxy config | קצר | main.py + vite.config.ts |
| P3 | Sound alerts | קצר | alertSound.ts |
| P3 | Export/report | בינוני | API + PrintView |
| P3 | Bed notes | בינוני | API + UI |
| P3 | God Mode PIN auth | בינוני | middleware |
| P3 | Docker production build (nginx) | בינוני | Dockerfile.frontend + nginx.conf |
| P3 | Security (authN/authZ critical endpoints) | ארוך | middleware + roles |
| P4 | Loading splash screen | בינוני | frontend |
| P4 | Full-screen mode | קצר | useFullscreen.ts |
| P4 | Risk trend indicator | קצר | BedState + BedCard |

---

### 11.19 — פיצ'רים מהגרסה המקורית: SentinelFetal → SentinelFetal2 (Known Gaps)

הפיצ'רים הבאים קיימים ב-SentinelFetal המקורי ואינם בתוכנית הנוכחית. כל אחד מסווג לפי עדיפות לפרודקשן:

#### MHR Contamination Detection — P2
בפרמוניטורינג חי, החיישן יכול לתפוס את דופק האם במקום הפטוס. בגרסה זו אנו עובדים עם הקלטות CTU-UHB שעברו QA — MHR contamination פחות רלוונטית כאן. עבור מעבר לפרמוניטורינג חי בעתיד: יש להוסיף rule ב-`src/rules/` שמזהה FHR בטווח 50–100 bpm ומוציא `mhr_alert: bool` ב-`BedState`.

#### Explainability — TrendPanel, FindingsPanel, CTG Highlight Regions — P2
ה-`DetailView` כולל `FindingsPanel.tsx` במבנה הקבצים של סקשן 7 — **יש לוודא שהוא מוטמע בפועל** עם:
- אזורים מסומנים על גרף CTG (deceleration markers, sinusoidal annotations)
- כיוון סיכון (`risk_delta`) כלשהו מוצג בכרטיס
- הסבר קצר לתוצאת ה-AI (אילו features תרמו)

#### i18n / RTL Support (EN/HE) — P3
ה-UI משתמש בטקסט בעברית/אנגלית עשוי להטריד בסביבה mixes. עדיף: טקסטים מוגדרים ב-`i18n/` עם `document.dir = 'rtl'` אוטומטי. **בשלב MVP: לא קריטי — כל הטקסטים בממשק в עברית בלבד היא קבלה.**

#### WebSocket Observability (`/ws/stats`, `/ws/health`) — P3
כלים לניטור מספר לקוחות מחוברים, גודל תור, latency. שימושי בdebug אבל לא קריטי ל-MVP.

#### E2E Testing (Playwright) — P2
**זה חסר משמעותי.** בלי E2E, רגרסיות בזרימת WS → chart לא יתגלו לפני פרודקשן. יש להוסיף:
```
frontend/e2e/
  ├── ward_view.spec.ts       ← 16 beds display, connect
  ├── detail_view.spec.ts     ← CTG chart renders, risk updates
  ├── simulation.spec.ts      ← start/stop/speed controls
  └── god_mode.spec.ts        ← PIN, injection, detection
```
מופעל ב-CI לפני כל push לmain.

#### Ward View Search/Filter/Sort — P3
**בינתיים:** מיון אוטומטי לפי risk_score (כרטיסים הכי מסוכנים ראשonים) מספיק לtriage בסיסי. תוספות נוחות: חיפוש לפי bed_id, filter לפי `alert=true`, grid presets (1/4/9/16). **לא P0 — ניתן לSprint 2.**

---

*תכנית זו מוכנה לביצוע. כל שלב אמאי ועצמאי — ניתן לבנות ולבדוק כל אחד לפני שממשיכים לבא.*

---

## שלב 7 — 4 Hz Chart Streaming (הפרדת גרף מ-Inference)

**תאריך:** 2026-03-07 | **מצב:** ✅ הושלם

### הבעיה

גרף ה-CTG "קפא" כל ~6 שניות ואז קיבל burst של 24 נקודות בבת אחת.
**סיבת שורש:** `_INFERENCE_STRIDE = 24` — ה-pipeline מחשב רק כל 24 דגימות (= 6 שניות ב-4 Hz).
נתוני הגרף (fhr_latest / uc_latest) הגיעו בתוך הודעת ה-BedState, כלומר גם הם ב-6 שניות פעם.

### הפתרון

הפרדה מלאה בין שני זרמים:
- **Inference stream** — BedState כל 6 שניות (ללא שינוי)
- **Chart tick stream** — דגימה בודדת לכל מיטה ב-4 Hz, ללא תלות ב-inference

### שינויי קוד

**`api/services/broadcaster.py`**
- `push()` מוסיף `"_kind": "state"` לפני הכנסה לתור
- שיטה חדשה `push_chart_tick(bed_id, fhr_bpm, uc_mmhg, t)` — מכניסה `{"_kind": "tick", ...}` לתור (thread-safe, `queue.put_nowait`, מוריד tick אם התור מלא)
- `_drain_loop()` מפריד queue ל-`bed_states` ו-`chart_ticks` ושולח שניהם בהודעת `batch_update` אחת

**`api/services/pipeline_manager.py`**
- `_process_and_broadcast()` — לפני בדיקת `if state is None: return`, תמיד פולט chart tick:
  ```python
  t = pipeline.current_sample_count / 4.0
  fhr_bpm = round(fhr_norm * 160.0 + 50.0, 1)
  uc_mmhg = round(uc_norm * 100.0, 1)
  self._broadcaster.push_chart_tick(pipeline.bed_id, fhr_bpm, uc_mmhg, t)
  ```

**`frontend/src/types/index.ts`**
- ממשק חדש `ChartTick { bed_id, fhr, uc, t }`
- `BatchUpdateMessage` מכיל `chart_ticks: ChartTick[]`

**`frontend/src/hooks/useBedStream.ts`**
- הוסרה השליחה הישנה של גרף דרך `fhr_latest`/`uc_latest`
- נוספה לולאה על `msg.chart_ticks` שמפרסמת כל tick ל-`chartUpdateBus`

---

## שלב 8 — Chart History Buffer (כל המיטות מוקלטות תמיד)

**תאריך:** 2026-03-07 | **מצב:** ✅ הושלם

### הבעיה

`chartUpdateBus` היה pub/sub פשוט ללא זיכרון — רק המנוי הפעיל קיבל נתונים.
כשהמשתמש צופה ב-DetailView של מיטה אחת, שאר המיטות לא היה להן מנוי — נתוני הגרף שלהן אבדו.
כשפתחו מיטה אחרת מאוחר יותר — הגרף התחיל מאפס.

### הפתרון

**`frontend/src/utils/chartUpdateBus.ts`** — כתיבה מחדש מלאה עם ring buffer לכל מיטה:

- `MAX_BUFFER = 4800` — 20 דקות × 4 Hz ≈ 115 KB סה"כ ל-4 מיטות
- `publish()` — תמיד שומר בבאפר, ללא קשר למנוי
- `subscribe()` — מיד מנגן מחדש את כל ההיסטוריה בתור קריאה אחת לcallback, אחר כך ממשיך עם ticks חיים
- Ring buffer מגביל ל-MAX_BUFFER (שומר הכי חדש), מונע דליפת זיכרון

### תוצאה

- פותחים כל מיטה בכל עת → גרף מציג מיד היסטוריה מלאה
- כל 4 המיטות מוקלטות תמיד ברקע
- אין שינויים ב-`useCTGChart.ts` — הוא כבר תומך במערכים באורך משתנה

# SentinelFetal2 — שלבי עבודה לסוכנים

**גרסה:** 1.0 | **מבוסס על:** PLAN.md v2.0  
**כלל:** כל שלב מבוצע על-ידי סוכן אחד, בסדר הכתוב. אל תתחיל שלב לפני שהשלב הקודם הושלם ובדיקותיו עברו.  
**אסור:** לשנות את PLAN.md. המקור האמין היחיד הוא PLAN.md — קרא אותו לפני כל שלב.

---

## סדר ביצוע

```
Phase 1 ─── src/inference/pipeline.py
    │
Phase 2 ─── generator/replay.py
    │
Phase 3 ─── api/  (FastAPI backend)
   / \
Phase 4   Phase 5
God Mode  Frontend
Backend   Core
    │         │
Phase 6 ──────┘
God Mode Frontend
    │
Phase 7 ─── scripts/ + Docker
    │
Phase 8 ─── Integration & Tests
```

---

## Phase 1 — `src/inference/pipeline.py`

**תלויות:** ללא (עובד על קוד קיים ב-`src/`)  
**קבצים לקרוא לפני הכתיבה:** PLAN.md §1, §2, §11.1 (BUG-1 עד BUG-7), §11.15  
**פלט:** קובץ אחד — `src/inference/pipeline.py`

### מה לממש

#### `BedState` dataclass
כל השדות כמפורט ב-PLAN.md §2 + תוספות מ-§10.7 ו-§11.15:
```
bed_id, recording_id, timestamp, elapsed_seconds
fhr_latest (24 ערכים — last stride. ראה BUG-7), uc_latest (24 ערכים)
risk_score, alert, alert_threshold
sample_count
god_mode_active: bool = False
active_events: list = field(default_factory=list)
risk_delta: float = 0.0
last_update_server_ts: float = field(default_factory=time.time)
```
> **חשוב BUG-7:** `fhr_latest = list(fhr_arr)[-24:]` — **24 ערכים, לא 16**.

#### `SentinelRealtime` class
- `__init__`: טוען 5 fold-weights מ-production_config, scaler, LR, threshold (`best_at`).
  - `self._state_lock = threading.Lock()` (BUG-5)
  - `god_mode: bool = False` + `self._injector = GodModeInjector.get() if god_mode else None`
  - **אסור:** לאחסן `self._loop` — לא נדרש כלל (BUG-8 תיקון).
- `on_new_sample(fhr_norm, uc_norm) -> BedState | None`
  - `with self._state_lock:` עוטף את כל הגוף
  - append לרינגים ב-`collections.deque(maxlen=7200)`
  - inference כל 24 samples לאחר warmup (`len >= 1800`)
  - קריאה ל-`_run_ensemble` — אם מחזירה `None`, מחזיר `None` (BUG-6)
- `_run_ensemble(signal: np.ndarray) -> float | None`
  - `try/except` מלא עם `logger.error` + `return None` (BUG-6)
- `_compute_full_state() -> BedState`
  - `stride = 24` (מ-production_config `"inference_stride": 24`)
  - `threshold = config["best_at"]` (= 0.4605, **לא** 0.4 מ-alert_extractor)
  - 25-feature vector: 12 AI + 11 clinical + 2 global
  - God Mode block: בדוק `has_active_events()` לפני ה-LR (ראה PLAN.md §10.6)
- `reset()` — `with self._state_lock:` מלא
- `current_sample_count` — `@property` מחזיר `self._sample_count` (BUG-3)

### בדיקה שהשלב הושלם
```python
# בוצע ידנית ב-Python REPL:
from src.inference.pipeline import SentinelRealtime, BedState
p = SentinelRealtime(bed_id="test", recording_id="1001", config=cfg)
# שלח 1824 samples (warmup + stride):
for i in range(1824):
    result = p.on_new_sample(0.5, 0.3)
assert result is not None                       # BedState הוחזר
assert len(result.fhr_latest) == 24             # BUG-7
assert isinstance(result.risk_score, float)
assert 0.0 <= result.risk_score <= 1.0
assert result.god_mode_active is False
assert result.risk_delta == 0.0 or isinstance(result.risk_delta, float)
```

---

## Phase 2 — `generator/replay.py`

**תלויות:** Phase 1 (ייבוא `BedState` לא נדרש — אבל כדאי לוודא שסביבה עובדת)  
**קבצים לקרוא לפני הכתיבה:** PLAN.md §3, §11.5  
**פלט:** קובץ אחד — `generator/replay.py` (החלף את הקיים)

### מה לממש

#### `RecordingReplay`
- `__init__(recording_id, recordings_dir)`: טוען `.npy` → `shape (2, N)`, מנורמל [0,1]
- `get_next_sample() -> tuple[float, float]`:
  - **Docstring חייב לומר:** `Returns (fhr_norm, uc_norm) — normalized [0,1]` (BUG-1)
  - wrap-around: עוטף לתחילת ה-recording אחרי הסוף
  - NaN: החלף ב-`0.0` לפני החזרה
- `reset()`: אפס position לתחילה

#### `ReplayEngine`
- `__init__(beds: dict[str, str], recordings_dir, callback, speed=1.0)`:
  - `beds` — מיפוי `bed_id → recording_id`
  - `callback(bed_id, fhr_norm, uc_norm)` — נקרא לכל sample (non-blocking! ראה Phase 3)
  - `speed` — [1.0, 20.0] (ראה §11.5)
- `add_bed(bed_id, recording_id)` / `remove_bed(bed_id)`
- `set_speed(speed: float)`:
  - `assert 1.0 <= speed <= 20.0`
  - thread-safe (atomic assign — float כתיבה אטומית ב-Python)
- `async run()`:
  - **חייב לעטוף iteration ב-`list(self._beds.items())`** — snapshot כדי למנוע RuntimeError מ-concurrent modification (BUG-4 מ-§11.1)
  - לולאה: `ticks_this_cycle = max(1, round(self._speed))` ticks per 0.25s
  - כל tick קורא `callback` — לא קורא ל-`pipeline.on_new_sample` ישירות
  - `asyncio.sleep(max(0.0, 0.25 - elapsed))`
- `pause()` / `resume()` / `stop()`

### בדיקה שהשלב הושלם
```python
import asyncio
from generator.replay import RecordingReplay, ReplayEngine

replay = RecordingReplay("1001", "data/recordings")
fhr, uc = replay.get_next_sample()
assert 0.0 <= fhr <= 1.0 and 0.0 <= uc <= 1.0

samples_received = []
def cb(bed_id, fhr, uc):
    samples_received.append((bed_id, fhr, uc))

engine = ReplayEngine({"bed_01": "1001"}, "data/recordings", cb, speed=1.0)

async def test():
    import asyncio
    task = asyncio.create_task(engine.run())
    await asyncio.sleep(1.0)      # 1 שנייה = ~4 samples ב-1x
    engine.stop()
    await task

asyncio.run(test())
assert len(samples_received) >= 3
assert samples_received[0][0] == "bed_01"
```

---

## Phase 3 — FastAPI Backend (`api/`)

**תלויות:** Phase 1 + Phase 2  
**קבצים לקרוא לפני הכתיבה:** PLAN.md §4, §9, §11.2, §11.3, §11.4, §11.5, §11.7, §11.8, §11.14, §11.16  
**פלט:** כל תיקיית `api/` + `scripts/validate_artifacts.py`

> **אל תממש God Mode endpoints בשלב זה** — הם שייכים לPhase 4.

### קבצים לכתוב

```
api/
├── __init__.py
├── main.py                  ← lifespan, app factory, health endpoint
├── config.py                ← Settings (pydantic-settings), includes god_mode_pin, god_mode_enabled
├── dependencies.py          ← get_manager(), get_broadcaster()
├── logging_config.py        ← setup_logging() — RotatingFileHandler + audit logger
├── models/
│   └── schemas.py           ← BedUpdate, BedSnapshot, RecordingInfo, AlertEvent, BedNote,
│                               EventAnnotationSchema — כולם Pydantic v2
├── middleware/
│   └── __init__.py          ← (ריק כרגע; god_mode_guard בשלב הבא)
├── routers/
│   ├── __init__.py
│   ├── simulation.py        ← /api/simulation/start|stop|pause|resume|speed|status
│   ├── beds.py              ← /api/beds, /api/beds/{id}, /api/beds/{id}/history,
│   │                           /api/beds/{id}/alerts, /api/beds/{id}/notes,
│   │                           /api/beds/{id}/export, /api/beds/config
│   ├── websocket.py         ← /ws/stream + initial_state on connect (§11.2)
│   ├── recordings.py        ← GET /api/recordings (§11.2)
│   └── system.py            ← GET /api/system/startup-status (SSE, §11.8)
└── services/
    ├── __init__.py
    ├── model_loader.py      ← load_models(config) → list[torch.nn.Module], scaler, lr
    ├── pipeline_manager.py  ← PipelineManager (§4 + §9 + בדיקות)
    ├── broadcaster.py       ← AsyncBroadcaster: push() sync, heartbeat loop (§11.4)
    ├── alert_history.py     ← AlertHistoryStore (§11.3)
    └── note_store.py        ← BedNote + NoteStore (§11.12)

scripts/
└── validate_artifacts.py    ← (§11.14) בדיקת artifacts ב-build time
```

### נקודות מפתח לממש

**`api/main.py` — lifespan:**
```
1. setup_logging()
2. validate_config (production_config.json)
3. load_models → model_loader
4. broadcaster = AsyncBroadcaster()
5. manager = PipelineManager(broadcaster, models, ...)
6. engine = ReplayEngine(..., callback=manager.on_sample)
7. בדיקת recordings_dir ≥ 1 .npy קובץ — RuntimeError אם חסר
8. asyncio.create_task(engine.run())
9. asyncio.create_task(broadcaster.run())
```

**`PipelineManager`:**
- `__init__(broadcaster, models, scaler, lr, config)` — **broadcaster מגיע ראשון** (BUG-2)
- `_executor = ThreadPoolExecutor(max_workers=4)`
- `on_sample(bed_id, fhr, uc)`: `self._executor.submit(self._process_and_broadcast, ...)` — מחזיר מיידית
- `_process_and_broadcast(pipeline, fhr, uc)`: קורא `pipeline.on_new_sample` → אם מחזיר state: `alert_history.record(state)` + `broadcaster.push(state)`
- **אסור:** `self._loop`, `run_coroutine_threadsafe` — push() הוא sync ו-thread-safe
- `enable_god_mode()` — system-wide toggle (BUG-4)
- `get_bed_states() -> list[BedState]` — snapshot לכל הלידות (לWebSocket initial_state)
- `get_pipeline(bed_id) -> SentinelRealtime | None`

**`AsyncBroadcaster`:**
- `push(state: BedState)`: `self._queue.put_nowait(state)` — **סינכרוני, thread-safe** (ראה §9)
- `async run()`: אוסף מה-queue, mounts ל-batch, שולח `{"type":"batch_update","updates":[...]}`
- `async _heartbeat_loop()`: כל 5 שניות שולח `{"type":"heartbeat","ts":...}` (§11.4)

**`/ws/stream` — initial state:**
```python
await websocket.accept()
client_id = await broadcaster.register(websocket)
current_states = manager.get_bed_states()
await websocket.send_json({"type": "initial_state", "beds": [...]})
```

### בדיקה שהשלב הושלם
```bash
# הרץ מתוך שורש הפרויקט:
uvicorn api.main:app --port 8000

# בדיקות בסיסיות (curl / httpx):
curl http://localhost:8000/api/health
# → {"status": "ok"}

curl -X POST http://localhost:8000/api/simulation/start \
  -d '{"beds": [{"bed_id":"bed_01","recording_id":"1001"}]}' \
  -H "Content-Type: application/json"

curl http://localhost:8000/api/beds
# → רשימה עם bed_01

curl http://localhost:8000/api/recordings
# → רשימה עם כל ה-.npy מ-data/recordings/

# WebSocket smoke test (Python):
import asyncio, websockets, json
async def test():
    async with websockets.connect("ws://localhost:8000/ws/stream") as ws:
        msg = json.loads(await ws.recv())
        assert msg["type"] == "initial_state"  # initial_state מגיע מיידית
        msg2 = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
        assert msg2["type"] in ("batch_update", "heartbeat")
asyncio.run(test())
```

---

## Phase 4 — God Mode Backend ✅ COMPLETED

**תלויות:** Phase 1 (SentinelRealtime + BedState) + Phase 3 (api/ running)
**קבצים לקרוא לפני הכתיבה:** PLAN.md §10, §11.6, docs/god_mode_signal_plan.md
**פלט:** `src/god_mode/` + `api/routers/god_mode.py` + `api/middleware/god_mode_guard.py`

> **גישה:** דו-שכבתית — **Signal Swap** (החלפת הקלטה) + **Feature Override** (זיהוי מיידי).
> ראה `docs/god_mode_signal_plan.md` לתיעוד מלא.

### שלב מקדים — בניית קטלוג פתולוגיות (חד-פעמי)

לפני הרצת המערכת, חובה לייצר את קטלוג הפתולוגיות:

```bash
python scripts/catalog_pathologies.py
# → data/god_mode_catalog.json נוצר (552 הקלטות נסרקו, 9 סוגי אירועים)
```

### קבצים לכתוב

```
scripts/
└── catalog_pathologies.py     ← סריקת 552 הקלטות, מייצר data/god_mode_catalog.json

src/god_mode/
├── __init__.py
├── types.py              ← EventType (Enum), InjectionEvent, EventAnnotation
├── injector.py           ← GodModeInjector (singleton, thread-safe)
├── overrides.py          ← build_feature_override() לכל EventType
└── segment_store.py      ← SegmentStore (catalog loader + segment selection)

api/routers/god_mode.py   ← /api/god-mode/inject|events|clear|enable|status
api/middleware/god_mode_guard.py  ← PIN auth middleware (§11.6)
```

### נקודות מפתח לממש

**`src/god_mode/types.py`:**
- `EventType(str, Enum)` — 9 סוגים (PLAN.md §10.3)
- `InjectionEvent` dataclass — כל השדות + `create()` classmethod
  - **שדות חדשים:** `original_recording_id: str | None = None`, `signal_swapped: bool = False`
- `EventAnnotation` dataclass — כל השדות

**`src/god_mode/injector.py` — `GodModeInjector`:**
- Singleton pattern (`_instance`)
- `has_active_events(bed_id, current_sample)` — **O(1) ללא lock** (חשוב לביצועים)
- `compute_override(...)` — **`with self._lock:`** עוטף הכל
- window boost check: `s + 1800 >= event.start_sample` — **לא** `s >= event.start_sample` (BUG-9)
- `add_event`, `end_event`, `get_event`, `clear_bed`, `get_events`
  - `clear_bed(bed_id)` מחזיר את הרשימה שנמחקה — לשחזור הקלטה
  - `get_event(bed_id, event_id)` — עוזר לשחזר `original_recording_id` בסיום

**`src/god_mode/overrides.py`:**
- `build_feature_override(clin, event) -> list[float]`
- כל 9 EventTypes עם override values (ראה PLAN.md §10.5)
- **רק מעלים ערכים, אף פעם לא מוריד** (חוץ מ-BRADYCARDIA/LOW_VARIABILITY שמורידים ספציפית)

**`src/god_mode/segment_store.py` — `SegmentStore`:**
- טוען `data/god_mode_catalog.json` בזמן startup
- `get_segment(event_type: str) -> dict | None` — בוחר אקראית מ-top 3 matches
- `has_segments(event_type)`, `available_types()`
- **Graceful fallback:** אם הקטלוג לא קיים — logs warning, ממשיך ללא signal swap

**שילוב ב-`SentinelRealtime._compute_full_state`:**
- הוסף God Mode block לאחר חישוב features (ראה PLAN.md §10.6)
- BedState מחזיר `god_mode_active`, `active_events`

**`api/services/pipeline_manager.py` — הוסף:**
```python
# ב-__init__:
self._segment_store = None
try:
    from src.god_mode.segment_store import SegmentStore
    self._segment_store = SegmentStore()
except Exception as exc:
    logger.info("SegmentStore not available: %s", exc)
```

**`api/routers/god_mode.py`:**
- `POST /api/god-mode/inject`: גישה דו-שכבתית:
  1. מנסה signal swap: `segment_store.get_segment(event_type)` → `engine.swap_recording()`
  2. שומר `original_recording_id` ב-InjectionEvent
  3. מוסיף feature override ל-injector
  - **תגובה:** `{"event_id": "...", "status": "injected", "signal_swapped": true, "start_sample": N}`
- `DELETE /api/god-mode/events/{event_id}`: קורא `end_event` + מחזיר הקלטה אם `original_recording_id` קיים
- `GET /api/god-mode/events?bed_id=`: מחזיר list
- `DELETE /api/god-mode/clear/{bed_id}`: מנקה + מחזיר הקלטה לאחרון שהוזרק
- `POST /api/god-mode/enable`: מאפשר God Mode system-wide
- `GET /api/god-mode/status`: מחזיר `{enabled, signal_swap_available, available_event_types}`

**`api/middleware/god_mode_guard.py`:**
- `GodModeGuard(BaseHTTPMiddleware)`
- hash-compare PIN מ-`X-God-Mode-Pin` header (SHA-256 + constant-time compare)
- 403 אם שגוי, סקיפ אם endpoint לא מתחיל ב-`/api/god-mode`

**`generator/replay.py` — הוסף:**
- `RecordingReplay.seek(sample_index)` — עיבוד לפוזיציה ספציפית
- `ReplayEngine.swap_recording(bed_id, recording_id, start_sample=0) -> str | None` — מחליף recording mid-stream, מחזיר את ה-ID הקודם

**רישום ב-`api/main.py`:**
```python
from api.routers import god_mode as god_mode_router
from api.middleware.god_mode_guard import GodModeGuard

app.add_middleware(GodModeGuard, pin=settings.god_mode_pin)
app.include_router(god_mode_router.router)
```

### בדיקה שהשלב הושלם
```bash
# God Mode מונה אסור ללא PIN:
curl -X POST http://localhost:8000/api/god-mode/inject \
  -d '{"bed_id":"bed_01","event_type":"late_decelerations","severity":0.85}' \
  -H "Content-Type: application/json"
# → 403 Unauthorized

# God Mode עם PIN:
curl -X POST http://localhost:8000/api/god-mode/inject \
  -d '{"bed_id":"bed_01","event_type":"late_decelerations","severity":0.85}' \
  -H "Content-Type: application/json" \
  -H "X-God-Mode-Pin: 1234"
# → {"event_id": "...", "status": "injected", "signal_swapped": true, "start_sample": N}

# בדיקת status:
curl http://localhost:8000/api/god-mode/status \
  -H "X-God-Mode-Pin: 1234"
# → {"enabled": true, "signal_swap_available": true, "available_event_types": [...9 types...]}

# תוך 6 שניות, ה-WebSocket אמור לשדר BedState עם:
# god_mode_active=True, active_events=[...], risk_score > 0.46
# הגרף מציג נתוני CTG מהקלטה פתולוגית אמיתית

# סיום אירוע + שחזור הקלטה:
curl -X DELETE "http://localhost:8000/api/god-mode/events/{event_id}?bed_id=bed_01" \
  -H "X-God-Mode-Pin: 1234"
# → {"status": "ended", "recording_restored": true}
```

---

## Phase 5 — Frontend Core (React)

**תלויות:** Phase 3 (backend רץ על port 8000)  
**קבצים לקרוא לפני הכתיבה:** PLAN.md §5, §8, §9 (frontend sections), §11.2, §11.4, §11.10  
**פלט:** כל תיקיית `frontend/` (ללא God Mode components — אלה ב-Phase 6)

### קבצים לכתוב

```
frontend/
├── package.json             ← dependencies כמפורט ב-PLAN.md נספח
├── vite.config.ts           ← proxy /api → localhost:8000, /ws → ws://localhost:8000
├── tailwind.config.js
├── postcss.config.js
├── tsconfig.json
├── index.html
└── src/
    ├── App.tsx              ← Router: / → WardView, /bed/:id → DetailView
    ├── types/
    │   └── index.ts         ← BedState TS, BedUpdate, WSMessage (union type — §11.2),
    │                           EventAnnotation, InitialStateMessage, BatchUpdateMessage,
    │                           HeartbeatMessage
    ├── services/
    │   └── wsClient.ts      ← WebSocket singleton connect/disconnect
    ├── stores/
    │   ├── bedStore.ts      ← Zustand: beds Map, RingBuffer per bed,
    │   │                       updateFromWebSocket(), initializeFromSnapshot()
    │   └── uiStore.ts       ← simulationRunning, speed, godModeUnlocked, godModePin
    ├── hooks/
    │   ├── useBedStream.ts  ← WebSocket connect, parse WSMessage (as WSMessage — typed cast),
    │   │                       dispatch to bedStore + chartUpdateBus
    │   ├── useCTGChart.ts   ← subscribe ל-chartUpdateBus, series.update() O(1)
    │   ├── useStaleDetector.ts  ← §11.4: detects > 15s without update
    │   └── useFullscreen.ts    ← §11.13
    ├── utils/
    │   ├── ringBuffer.ts       ← RingBuffer<T> class (push, toArray, size)
    │   └── chartUpdateBus.ts   ← ChartUpdateBus singleton (BUG-10)
    └── components/
        ├── layout/
        │   └── AppHeader.tsx   ← כותרת, status, fullscreen button, speed controls
        ├── ward/
        │   ├── WardView.tsx    ← grid 4×4, sorted by risk_score desc
        │   └── BedCard.tsx     ← React.memo, risk bar (B&W), stale badge, alert border
        ├── detail/
        │   ├── DetailView.tsx  ← layout: header + CTG chart + panels
        │   ├── CTGChart.tsx    ← lightweight-charts container, useCTGChart hook
        │   ├── RiskGauge.tsx   ← progress bar + score + delta arrows (§11.15)
        │   ├── FindingsPanel.tsx  ← 11 clinical features
        │   └── AlertHistory.tsx   ← list of alert transitions
        └── common/
            ├── StatusBadge.tsx    ← LIVE / STALE / ALERT badges
            └── SimulationControls.tsx  ← start/stop/pause/resume + speed [1×][2×][5×][10×]
```

### נקודות מפתח לממש

**`src/types/index.ts` — WSMessage union (§11.2):**
```typescript
export type WSMessage =
  | { type: 'initial_state'; beds: BedState[] }
  | { type: 'batch_update'; updates: BedUpdate[]; timestamp: number }
  | { type: 'heartbeat'; ts: number }
```

**`useBedStream.ts`:**
```typescript
const msg = JSON.parse(event.data) as WSMessage   // typed cast
if (msg.type === 'initial_state') { store.initializeFromSnapshot(msg.beds) }
else if (msg.type === 'batch_update') {
  for (const u of msg.updates) {
    store.updateFromWebSocket(u)
    chartUpdateBus.publish(u.bed_id, u)   // עוקף React render cycle (BUG-10)
  }
}
```

**`chartUpdateBus.ts` (BUG-10):**
```typescript
// Singleton pub/sub — decouples lightweight-charts from React render
class ChartUpdateBus {
  private subs = new Map<string, Set<(u: BedUpdate) => void>>()
  subscribe(bedId: string, fn: (u: BedUpdate) => void) { ... }
  unsubscribe(bedId: string, fn: (u: BedUpdate) => void) { ... }
  publish(bedId: string, u: BedUpdate) { ... }
}
export const chartUpdateBus = new ChartUpdateBus()
```

**`useCTGChart.ts` (BUG-10):**
```typescript
useEffect(() => {
  const handler = (u: BedUpdate) => {
    for (const [fhr, uc, t] of zipSamples(u.fhr_latest, u.uc_latest, u.timestamp)) {
      fhrSeries.update({ time: t, value: fhr * 160 + 50 })   // denorm for display
      ucSeries.update({ time: t, value: uc * 100 })
    }
  }
  chartUpdateBus.subscribe(bedId, handler)
  return () => chartUpdateBus.unsubscribe(bedId, handler)
}, [bedId])
```

**עיצוב B&W בלבד (§8):** השתמש אך ורק ב-palette מה-PLAN.md — אין כחול, אדום, ירוק.  
- Alert state: `border-2 border-gray-900` (כרטיס)  
- Risk bar: `bg-gray-200` → `bg-gray-700` → `bg-gray-900`  
- Trend arrows: `font-bold text-gray-900` (עולה) / `text-gray-400` (יורד)  
- Stale: `opacity-60` + badge אפור

### בדיקה שהשלב הושלם
```bash
cd frontend
npm install
npm run dev
# פתח http://localhost:5173

# בדיקות ידניות:
# 1. WardView מציג 16 כרטיסי לידה (לאחר /api/simulation/start)
# 2. CTG chart מתעדכן בזמן אמת (grf נע שמאלה)
# 3. Risk gauge מציג ציון + חץ
# 4. לחיצה על כרטיס → DetailView
# 5. Speed controls עובדים (2x מהיר פי 2)
# 6. Stale badge מופיע אחרי 15s ב-bed שנעצר

# TypeScript compile — חייב לעבור ללא שגיאות:
npm run build
```

---

## Phase 6 — God Mode Frontend

**תלויות:** Phase 4 (God Mode backend) + Phase 5 (Frontend core)  
**קבצים לקרוא לפני הכתיבה:** PLAN.md §10.9, §10.10, §10.12  
**פלט:** `frontend/src/components/god-mode/` + שינויים ב-`DetailView`, `stores/uiStore.ts`, `types/index.ts`

### קבצים לכתוב

```
frontend/src/components/god-mode/
├── GodModePanel.tsx      ← כפתורי הזרקה, slider עוצמה, בחירת משך, רשימת אירועים פעילים
├── DetectionDetail.tsx   ← modal/panel פרטי זיהוי (ראה PLAN.md §10.10)
└── EventJournal.tsx      ← טבלת היסטוריית אירועים
```

### תוספות לקבצים קיימים

**`frontend/src/stores/uiStore.ts`:**
```typescript
godModePin: string | null          // שמור ב-sessionStorage — נמחק בסגירת tab
godModeUnlocked: boolean
setGodModePin(pin: string): void
clearGodModePin(): void
```

**`frontend/src/types/index.ts` — הרחבות:**
```typescript
export interface EventAnnotation {
  event_id: string
  event_type: string
  start_sample: number
  end_sample: number | null
  still_ongoing: boolean
  description: string
  timeline_summary: string
  detected_details: Record<string, unknown>
}
// הוסף ל-BedUpdate:
god_mode_active?: boolean
active_events?: EventAnnotation[]
```

**`DetailView.tsx` — הוסף:**
1. `GodModePanel` מתחת ל-`RiskGauge` (מוצג רק כש-`god_mode_enabled`)
2. סמני ציר זמן על `CTGChart` כשיש `active_events`:
   - `▼` ב-`start_sample` (marker ב-lightweight-charts)
   - `▲` ב-`end_sample` (אם קיים)
   - קו אנכי `►` אם `still_ongoing`
3. `EventJournal` מתחת לגרף

**`GodModePanel.tsx` — פונקציונליות:**
- 9 כפתורי EventType
  - בטעינה: קרא `GET /api/god-mode/status` כדי לדעת אילו types יש להם catalog entries
  - כפתורים עם catalog: ★ marker (signal swap אמיתי)
  - כפתורים ללא catalog: opacity מופחת + tooltip "feature override only"
- Slider עוצמה (0.5–1.0, step 0.05)
- בחירת משך: dropdown `[1 min, 2 min, 5 min, 10 min, Ongoing]`
- כפתור "הזרק אירוע" → `POST /api/god-mode/inject` עם header `X-God-Mode-Pin`
  - אם response כולל `signal_swapped: true` — הצג badge "📡 Signal" על האירוע הפעיל
  - אם `signal_swapped: false` — הצג "Feature override only"
- רשימת אירועים פעילים עם:
  - badge "📡 Signal" אם `signal_swapped`
  - כפתור "עצור" → `DELETE /api/god-mode/events/{id}?bed_id=...`
  - כשמוחזר `recording_restored: true` — הצג toast "הקלטה מקורית שוחזרה"
- PIN entry modal: אם `!godModeUnlocked`, מציג שדה PIN לפני כל פעולה

**`frontend/src/types/index.ts` — הוסף ל-InjectResponse:**
```typescript
export interface InjectResponse {
  event_id: string
  status: string
  signal_swapped: boolean   // ← חדש: האם הקלטה הוחלפה
  start_sample: number
}

export interface GodModeStatus {
  enabled: boolean
  signal_swap_available: boolean
  available_event_types: string[]   // ← event types עם catalog entries
}
```

### בדיקה שהשלב הושלם
```
1. פתח DetailView ל-bed_01
2. ודא כפתורי EventType עם ★ (catalog available) מוצגים בבירור
3. לחץ "Late Decels" → PIN modal → הזן "1234" → לחץ "הזרק אירוע"
4. תוך 6 שניות: risk_score עולה > 0.46, god_mode_active=True
5. badge "📡 Signal" מוצג על האירוע הפעיל (signal_swapped=true)
6. הגרף מציג נתוני CTG שונים מקודם (הקלטה פתולוגית אמיתית)
7. סמן ▼ מופיע בנקודת ה-start על גרף ה-CTG
8. EventJournal מציג שורה עם "Late Decels | עדיין פעיל | 📡"
9. לחץ "עצור" → toast "הקלטה מקורית שוחזרה" → "משך: 00:XX:XX" מופיע
10. PIN שגוי → 403 מוצג כ-toast error (react-hot-toast)
```

---

## Phase 7 — Scripts & Docker

**תלויות:** Phases 1–6 כולם (deployment-ready)  
**קבצים לקרוא לפני הכתיבה:** PLAN.md §11.14, §11 רשימת dependencies  
**פלט:** Dockerfile, docker-compose.yml, frontend/Dockerfile.frontend, frontend/nginx.conf, .env.example

### קבצים לכתוב

**`scripts/validate_artifacts.py`** (PLAN.md §11.14):
- בדיקת `artifacts/production_config.json`
- בדיקת 5 weight files (torch.load עם `weights_only=True`)
- בדיקת `production_scaler.pkl` + `production_lr.pkl`
- **לא** בודק `data/recordings/` כאן — זה runtime check ב-lifespan
- `sys.exit(1)` עם הסבר אם כשל

**`Dockerfile`** (backend — Python 3.11-slim):
```dockerfile
FROM python:3.11-slim AS backend
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN python scripts/validate_artifacts.py   # fails build if artifacts missing
EXPOSE 8000
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
```

**`frontend/Dockerfile.frontend`** (multi-stage — **לא** dev server):
```dockerfile
FROM node:20-slim AS build
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
```

**`frontend/nginx.conf`** (SPA + proxy):
```nginx
server {
    listen 80;
    root /usr/share/nginx/html;
    index index.html;
    location / { try_files $uri $uri/ /index.html; }
    location /api/ { proxy_pass http://backend:8000; }
    location /ws/ {
        proxy_pass http://backend:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "Upgrade";
    }
}
```

**`docker-compose.yml`** (PLAN.md §11.14):
- volumes: `./data:/app/data`, `./weights:/app/weights`, `./logs:/app/logs`
- healthcheck על `GET /api/health`
- `GOD_MODE_PIN` + `GOD_MODE_ENABLED` env vars

**`.env.example`:**
```
GOD_MODE_PIN=change_me
GOD_MODE_ENABLED=false
LOG_LEVEL=info
```

**`requirements.txt` — וודא שנוספו:**
```
fastapi>=0.110
uvicorn[standard]>=0.29
pydantic>=2.0
pydantic-settings>=2.0
websockets>=12.0
```

### בדיקה שהשלב הושלם
```bash
# validate artifacts locally:
python scripts/validate_artifacts.py
# → ✓ All artifacts validated (5 folds)

# docker build (רק backend — frontend build ארוך):
docker build -t sentinel-backend .
# → חייב להצליח ללא שגיאות

# docker-compose up (אם Docker זמין):
docker-compose up --build
curl http://localhost:8000/api/health
# → {"status": "ok"}
```

---

## Phase 8 — Integration & Tests

**תלויות:** כל השלבים (1–7)  
**קבצים לקרוא לפני הכתיבה:** PLAN.md §6 (Smoke Tests + Integration Tests + Perf Test)  
**פלט:** קבצי בדיקות + `scripts/perf_test_16beds.py`

### קבצים לכתוב

```
tests/
├── test_pipeline.py         ← unit tests: BedState, on_new_sample, reset, lock, fallback
├── test_replay.py           ← unit tests: RecordingReplay wrap, NaN, ReplayEngine speed,
│                               seek(), swap_recording() (שדות חדשים — Phase 4)
├── test_broadcaster.py      ← unit tests: push() thread-safety, batch assembly
├── test_god_mode.py         ← unit tests: override math, window check (BUG-9), PIN guard,
│                               signal_swapped=True בתגובת inject, recording_restored בסיום
└── test_integration.py      ← smoke test: PLAN.md §6 integration flow

scripts/
└── perf_test_16beds.py      ← 16 beds × 60 sec: CPU%, memory, WS lag
```

### smoke test (`test_integration.py`) — בדיוק כפי שמוגדר ב-PLAN.md §6:
```python
import asyncio, pytest
from generator.replay import ReplayEngine
from src.inference.pipeline import SentinelRealtime

async def test_full_pipeline_smoke():
    results = []
    # 1. Init pipelines (ראה PLAN.md §6 לפרטים מלאים)
    pipelines = {f"bed_{i:02d}": SentinelRealtime(...) for i in range(1, 3)}

    def callback(bed_id, fhr, uc):
        state = pipelines[bed_id].on_new_sample(fhr, uc)
        if state: results.append(state)

    e = ReplayEngine({"bed_01": "1001", "bed_02": "1002"}, ..., callback)
    task = asyncio.create_task(e.run())   # e.run() — לא e._tick() (BUG תיקון §11.1.3)
    await asyncio.sleep(10)              # ~40 samples per bed
    e.stop()
    await task

    assert any(r.bed_id == "bed_01" for r in results)
    # values must be normalized [0,1] — NOT bpm (BUG תיקון §11.1.2):
    for r in results:
        assert 0.0 <= r.risk_score <= 1.0
        assert all(0.0 <= v <= 1.0 for v in r.fhr_latest)
```

**`test_god_mode.py` — כיסוי נדרש:**
```python
# signal swap — ReplayEngine
def test_swap_recording_returns_old_id():
    engine = ReplayEngine({"bed_01": "1001"}, ...)
    old = engine.swap_recording("bed_01", "1002", start_sample=500)
    assert old == "1001"
    # after swap, bed_01 plays from recording 1002
    assert engine._beds["bed_01"].recording_id == "1002"
    assert engine._beds["bed_01"]._pos == 500  # seek applied

def test_swap_recording_unknown_bed():
    engine = ReplayEngine({}, ...)
    result = engine.swap_recording("nonexistent", "1001")
    assert result is None   # graceful

# inject response includes signal_swapped
async def test_inject_response_includes_signal_swapped(client, mock_catalog):
    resp = await client.post("/api/god-mode/inject",
        json={"bed_id": "bed_01", "event_type": "late_decelerations", "severity": 0.85},
        headers={"X-God-Mode-Pin": "1234"})
    assert resp.status_code == 200
    data = resp.json()
    assert "signal_swapped" in data
    assert "start_sample" in data

# end_event restores recording
async def test_end_event_restores_recording(client):
    # inject → end → recording_restored=True
    inj = await client.post("/api/god-mode/inject", ...)
    event_id = inj.json()["event_id"]
    end = await client.delete(f"/api/god-mode/events/{event_id}?bed_id=bed_01", ...)
    assert end.json().get("recording_restored") in (True, False)   # field must exist
```

**`perf_test_16beds.py` — קריטריוני עמידה:**
```
CPU ≤ 40%
Memory ≤ 1 GB
WebSocket lag < 200ms (מ-push() עד קבלה ב-client)
No dropped frames (כל 24 samples מגיעים לfront-end)
```

### בדיקה שהשלב הושלם
```bash
python -m pytest tests/ -v
# → כל הבדיקות עוברות

python scripts/perf_test_16beds.py
# → כל קריטריוני הביצועים עוברים
```

---

## נספח: נקודות שימת לב בין-שלביות

| נושא | שלב | אזהרה |
|------|-----|-------|
| ערכים מנורמלים | 1, 2 | כל הנתונים [0,1] בכל מקום ב-backend. denorm רק ב-frontend לתצוגה (`bpm = v*160+50`) |
| `push()` is sync | 3 | **אף פעם** לא לקרוא `asyncio.run_coroutine_threadsafe` על `broadcaster.push` |
| `_loop` forbidden | 3 | **אסור** לאחסן `self._loop = asyncio.get_event_loop()` ב-`PipelineManager.__init__` |
| `executor.submit` | 3 | `on_sample` חייב להחזיר מיידית — כל inference ב-executor |
| `list(beds.items())` | 2 | snapshot לפני iteration ב-`ReplayEngine.run()` |
| BUG-7 `[-24:]` | 1 | `fhr_latest = list(arr)[-24:]` — 24 points per stride |
| BUG-9 window check | 4 | `s + 1800 >= event.start_sample` — לא `s >= event.start_sample` |
| threshold = best_at | 1 | השתמש ב-`config["best_at"]` (0.4605) — לא ב-`ALERT_THRESHOLD=0.4` מ-alert_extractor |
| God Mode default off | 3, 4 | `god_mode_enabled=False` ב-.env ו-settings |
| Frontend: no colors | 5, 6 | B&W בלבד. אם אתה כותב `text-red-*`, `bg-blue-*` וכו' — *זה שגוי* |
| Docker: no dev server | 7 | `frontend/Dockerfile.frontend` חייב להשתמש ב-nginx, לא `npm run dev` |
| validate_artifacts | 7 | מריץ ב-build time — **לא** בודק `data/recordings/` (זה runtime) |

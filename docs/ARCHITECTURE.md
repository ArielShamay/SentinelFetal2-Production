# SentinelFetal2 — Full System Architecture

This document describes, with full precision, every layer of the system:
how data moves from the `.npy` recording files all the way to pixels on the screen.
It is written so that anyone reading it can reason about timing, latency, and bugs
without needing to open source files.

---

## Table of Contents

1. [High-Level Overview](#1-high-level-overview)
2. [Backend — Data Pipeline](#2-backend--data-pipeline)
   - 2.1 [ReplayEngine (generator/replay.py)](#21-replayengine-generatorreplaypy)
   - 2.2 [PipelineManager (api/services/pipeline_manager.py)](#22-pipelinemanager-apiservicespipeline_managerpy)
   - 2.3 [SentinelRealtime (src/inference/pipeline.py)](#23-sentinelrealtime-srcinferencepipelinepy)
   - 2.4 [AsyncBroadcaster (api/services/broadcaster.py)](#24-asyncbroadcaster-apiservicesbroadcasterpy)
   - 2.5 [WebSocket Endpoint (api/routers/websocket.py)](#25-websocket-endpoint-apirouterswebsocketpy)
   - 2.6 [REST API Overview](#26-rest-api-overview)
   - 2.7 [FastAPI App + Lifespan (api/main.py)](#27-fastapi-app--lifespan-apimainpy)
3. [Two Separate Data Flows](#3-two-separate-data-flows)
4. [Frontend — Data Pipeline](#4-frontend--data-pipeline)
   - 4.1 [WebSocket Client (wsClient.ts)](#41-websocket-client-wsclientts)
   - 4.2 [useBedStream Hook](#42-usedbedstream-hook)
   - 4.3 [Zustand Store (bedStore.ts)](#43-zustand-store-bedstorets)
   - 4.4 [chartUpdateBus (chartUpdateBus.ts)](#44-chartupdatebus-chartupdatebustts)
   - 4.5 [RingBuffer (ringBuffer.ts)](#45-ringbuffer-ringbufferts)
   - 4.6 [useCTGChart Hook](#46-usectgchart-hook)
5. [Frontend — Component Tree](#5-frontend--component-tree)
   - 5.1 [App.tsx and Routing](#51-apptsx-and-routing)
   - 5.2 [WardView](#52-wardview)
   - 5.3 [BedCard](#53-bedcard)
   - 5.4 [DetailView](#54-detailview)
   - 5.5 [CTGChart Component](#55-ctgchart-component)
6. [Timing Budget and Latency Stack](#6-timing-budget-and-latency-stack)
7. [God Mode System](#7-god-mode-system)
8. [Performance Fixes Applied](#8-performance-fixes-applied)
9. [Data Formats and Normalization](#9-data-formats-and-normalization)
10. [File Map — Every Source File Explained](#10-file-map--every-source-file-explained)

---

## 1. High-Level Overview

```
  ┌────────────────────────────────────────────────────────────────┐
  │  data/recordings/*.npy  (pre-normalized CTG recordings)        │
  └─────────────────────────────┬──────────────────────────────────┘
                                │  4 Hz, normalized [0,1]
                                ▼
             ┌────────────────────────────────┐
             │  ReplayEngine (asyncio loop)   │  generator/replay.py
             │  TICK_INTERVAL = 0.25 s        │
             │  yields to event loop between  │
             │  ticks at high speed (sleep 0) │
             └────────────────┬───────────────┘
                              │  callback(bed_id, fhr_norm, uc_norm)
                              │  (non-blocking: submits to thread pool)
                              ▼
       ┌──────────────────────────────────────────┐
       │  PipelineManager                         │  api/services/pipeline_manager.py
       │  ThreadPoolExecutor(max_workers=8)        │
       │  Backpressure: max 50 pending/bed         │
       │                                          │
       │  on_sample() — event loop (fast path):   │
       │    1. increment _sample_counters[bed_id] │
       │    2. denormalize → fhr_bpm, uc_mmhg     │
       │    3. push_chart_tick() ← immediately    │
       │    4. executor.submit(inference task)    │
       │                                          │
       │  _process_and_broadcast() — thread pool: │
       │    pipeline.on_new_sample() → BedState   │
       └──────────┬───────────────────────────────┘
                  │                    │
   chart tick (event loop)    BedState (every 24 samples)
                  │                    │
                  ▼                    ▼
       ┌──────────────────────────────────────────────────┐
       │  AsyncBroadcaster              broadcaster.py    │
       │  _tick_queue  ← push_chart_tick() (event loop)  │
       │  _queue       ← push() (thread pool)            │
       │  drain loop: every 50ms                         │
       │  ward downsampling: ≤ 4 Hz per bed              │
       │  per-client focused_bed → detail ticks only     │
       └──────────────────────────┬───────────────────────┘
                                  │  WebSocket
                                  ▼
                    ┌────────────────────────┐
                    │  Browser (React SPA)   │
                    │  wsClient singleton    │
                    └────────────┬───────────┘
                                 │
                    ┌────────────┴────────────────────────────┐
                    │                                         │
            Inference updates               Chart ticks (ward + detail)
                    │                                         │
                    ▼                                         ▼
         Zustand bedStore               chartUpdateBus (two channels)
         (risk, clinical,               DETAIL: RingBuffer 4800 pts → useCTGChart
          fhrRing, ucRing)              WARD:   RingBuffer 120 pts  → Sparkline
                    │                                    │
                    ▼                                    ▼
              WardView /             WardView: Sparkline (canvas)
              DetailView UI          DetailView: useCTGChart + lightweight-charts
```

The system splits into **two independent data flows** at the event-loop level:

- **Flow A — Inference**: sample → thread pool → SentinelRealtime (PatchTST ensemble, every 24 samples) → BedState → Zustand store → React UI (risk scores, clinical features, alert state). Every 6 seconds per bed.
- **Flow B — Chart Ticks**: sample → `on_sample()` on event loop → `push_chart_tick()` → broadcaster `_tick_queue` → WebSocket → `chartUpdateBus` (detail + ward channels) → Sparkline canvas / lightweight-charts. Every sample, independent of inference load.

Flow B is **fully decoupled from Flow A**: chart ticks are pushed on the event loop before inference is submitted to the thread pool, so AI latency never delays the waveform display.

---

## 2. Backend — Data Pipeline

### 2.1 ReplayEngine (`generator/replay.py`)

**Purpose**: Reads `.npy` CTG recordings and feeds samples to the pipeline at exactly 4 Hz.

**Key constants**:
```python
TICK_INTERVAL = 0.25   # seconds between outer loop iterations
```

**Loop logic** (actual implementation):
```python
while self._running:
    if self._paused:
        await asyncio.sleep(0.1)
        continue

    t_start = asyncio.get_event_loop().time()
    ticks_this_cycle = max(1, round(self._speed))

    for tick_i in range(ticks_this_cycle):
        if not self._running:
            break
        for bed_id, replay in list(self._beds.items()):
            fhr, uc = replay.get_next_sample()
            self._callback(bed_id, fhr, uc)   # NON-BLOCKING by contract
        # Yield to event loop between ticks (prevents starvation at high speed)
        if tick_i < ticks_this_cycle - 1:
            await asyncio.sleep(0)

    self._tick_count += 1
    elapsed = asyncio.get_event_loop().time() - t_start
    await asyncio.sleep(max(0.0, TICK_INTERVAL - elapsed))
```

**Key design decision — `await asyncio.sleep(0)` between ticks**:
At speed 10×, `ticks_this_cycle = 10`. Without yielding, the event loop would be locked for 10 callback dispatches before the drain loop, heartbeat, or WebSocket sends could run. The `sleep(0)` between ticks costs negligible wall time but yields control to the event loop scheduler, preventing starvation at high speed multipliers (10–20×).

- At **speed 1×**: 1 sample per bed per 0.25 s = 4 Hz.
- At **speed N×**: N samples per bed per 0.25 s (compressed recording time), with N−1 yields per cycle.
- Speed range: 1.0 – 20.0, enforced in `set_speed()`.
- `beds_snapshot` — `list(self._beds.items())` snapshot prevents concurrent-modification if `set_beds()` is called mid-loop.

**RecordingReplay** (inner class):
- Loads a single `.npy` file on construction. Shape: `(2, T)` — channel 0 = FHR norm, channel 1 = UC norm.
- `get_next_sample()` returns `(fhr_norm, uc_norm)` and advances position.
- Loops infinitely: when position reaches end, resets to 0.
- `NaN` values replaced: `fhr_norm = 0.5` (= 130 bpm), `uc_norm = 0.0` (= 0 mmHg).

**Public API used by the rest of the system**:
- `set_beds(bed_configs)` — atomic replace of all beds (used by `POST /api/simulation/start`)
- `set_speed(speed)` — float assignment, CPython-atomic
- `swap_recording(bed_id, recording_id)` — replaces one bed's recording mid-stream
- `add_bed / remove_bed` — individual bed management
- `pause() / resume()` — suspend/resume loop

---

### 2.2 PipelineManager (`api/services/pipeline_manager.py`)

**Purpose**: Bridge between the async event loop and the CPU-intensive inference pipelines. Receives samples from the callback (called from the asyncio loop) and dispatches work to a thread pool.

**Key design**:
```python
self._executor = ThreadPoolExecutor(max_workers=8, thread_name_prefix="sentinel-inf")
self._pending: dict[str, int] = defaultdict(int)   # per-bed pending task counter
```

**`on_sample(bed_id, fhr_norm, uc_norm)` — called by ReplayEngine callback**:
This method is called from the asyncio event loop. It must return immediately (non-blocking). It submits `_process_and_broadcast_wrapped()` to the thread pool and returns.

```python
def on_sample(self, bed_id: str, fhr_norm: float, uc_norm: float) -> None:
    pipeline = self._pipelines.get(bed_id)
    if pipeline is None:
        return
    if self._pending[bed_id] >= 50:
        return  # backpressure — extreme load protection only
    self._pending[bed_id] += 1
    self._executor.submit(self._process_and_broadcast_wrapped, bed_id, pipeline, fhr_norm, uc_norm)
```

**Backpressure**: The `_pending` counter prevents unbounded `ThreadPoolExecutor` queue growth at very high speeds (15–20× with many beds). The limit of 50 is intentionally generous: it only activates at extreme load, while allowing enough throughput for warmup (1800 samples) and steady-state inference to proceed normally.

**`_process_and_broadcast_wrapped()` — wrapper for counter management**:
```python
def _process_and_broadcast_wrapped(self, bed_id, pipeline, fhr_norm, uc_norm):
    try:
        self._process_and_broadcast(pipeline, fhr_norm, uc_norm)
    finally:
        self._pending[bed_id] -= 1
```

**`_process_and_broadcast(pipeline, fhr_norm, uc_norm)` — runs in worker thread**:
```python
def _process_and_broadcast(self, pipeline, fhr_norm, uc_norm):
    # 1. Denormalize for display
    fhr_bpm = round(fhr_norm * 160.0 + 50.0, 1)
    uc_mmhg = round(uc_norm * 100.0, 1)
    # 2. Compute timestamp BEFORE inference  ← CRITICAL ORDER
    t = (pipeline.current_sample_count + 1) / 4.0
    # 3. Push chart tick FIRST (before inference blocks)
    self._broadcaster.push_chart_tick(pipeline.bed_id, fhr_bpm, uc_mmhg, t)
    # 4. Run inference (may take ~50–200ms every 24th sample for PatchTST)
    state = pipeline.on_new_sample(fhr_norm, uc_norm)
    # 5. Cache state and broadcast if inference produced a result
    if state is not None:
        with self._lock:
            self._last_states[state.bed_id] = state
        self._alert_history.record(state)
        self._broadcaster.push(state)
```

**Why chart tick is pushed BEFORE `on_new_sample()`**:
`on_new_sample()` may run PatchTST inference (~50–200 ms on every 24th sample). If the tick were pushed after, the chart tick for that sample would be delayed by ≈200ms on inference samples, creating non-uniform tick spacing visible in the waveform.

**`bed_id` public property on SentinelRealtime**:
`pipeline_manager.py` accesses `pipeline.bed_id` (public property), not `pipeline._bed_id` (private attribute). The property is defined in `src/inference/pipeline.py`:
```python
@property
def bed_id(self) -> str:
    return self._bed_id
```

---

### 2.3 SentinelRealtime (`src/inference/pipeline.py`)

**Purpose**: Per-bed real-time inference pipeline. Accumulates normalized FHR/UC samples in a ring buffer, runs the PatchTST ensemble every `_INFERENCE_STRIDE` samples, and returns a `BedState`.

**Key constants**:
```python
_WINDOW_LEN        = 1800   # 7.5 minutes @ 4 Hz — minimum samples before inference starts
_INFERENCE_STRIDE  = 24     # run inference every 24 samples = every 6 seconds
_RING_MAXLEN       = 7200   # ring buffer length = 30 minutes @ 4 Hz
_WINDOW_SCORE_MAX  = 300    # cap window_scores list: ~30 min of inference history
```

**`BedState` dataclass** (returned by `on_new_sample()`, or `None` during warmup / non-stride ticks):
```python
@dataclass
class BedState:
    bed_id: str
    recording_id: str
    timestamp: float
    risk_score: float          # 0.0–1.0
    alert: bool
    alert_threshold: float
    window_prob: float
    fhr_latest: list[float]    # last 24 FHR samples in BPM (denormalized)
    uc_latest: list[float]     # last 24 UC samples in mmHg (denormalized)
    baseline_bpm: float
    is_tachycardia: float      # 0.0 or 1.0
    is_bradycardia: float
    variability_amplitude_bpm: float
    variability_category: int
    n_late_decelerations: int
    n_variable_decelerations: int
    n_prolonged_decelerations: int
    max_deceleration_depth_bpm: float
    sinusoidal_detected: bool
    tachysystole_detected: bool
    elapsed_seconds: float
    warmup: bool
    sample_count: int
    god_mode_active: bool
    active_events: list
    risk_delta: float
    last_update_server_ts: float
```

**`on_new_sample(fhr_norm, uc_norm)` — the hot path**:
1. Appends to both ring buffers (FHR and UC, each `deque(maxlen=7200)`).
2. Increments `_sample_count`.
3. If `_sample_count < _WINDOW_LEN` → returns `None` (warmup).
4. If `_sample_count % _INFERENCE_STRIDE != 0` → returns `None` (non-stride tick).
5. **Converts deque → numpy ONCE**: `fhr_full = np.array(self._fhr_ring, dtype=np.float32)`. Both the inference window (`fhr_win = fhr_full[-_WINDOW_LEN:]`) and `_compute_full_state()` receive this same array — no double conversion.
6. Stacks FHR + UC → `(2, 1800)` input tensor → PatchTST ensemble → `risk_score`.
7. Appends `(start, prob)` to `_window_scores`; caps list at `_WINDOW_SCORE_MAX = 300`.
8. Calls `_compute_full_state(fhr_full, uc_full)` → clinical features + BedState.

**numpy optimization**: Converting `deque(maxlen=7200)` to numpy is O(N). Previously this was done twice per inference tick — once in `on_new_sample()` and again in `_compute_full_state()`. Now the conversion happens once and the result is passed as a parameter to `_compute_full_state(fhr_arr, uc_arr)`.

**`_window_scores` cap**: The list accumulates `(start_sample, probability)` tuples for every inference tick. Without a cap, after 10 hours of operation at 1× speed it would hold 6000 entries. It is now truncated to the last 300 entries (~30 minutes of inference history) using `self._window_scores = self._window_scores[-_WINDOW_SCORE_MAX:]`.

**Thread safety**:
`_state_lock` is a `threading.Lock`. It is held for the entire duration including PatchTST inference. With `max_workers=4`, up to 4 beds can run inference simultaneously.

---

### 2.4 AsyncBroadcaster (`api/services/broadcaster.py`)

**Purpose**: Bridges the thread pool / event loop (sync) and the asyncio WebSocket (async). Two separate queues prevent AI inference backpressure from delaying chart ticks. Ward downsampling limits wire load at high replay speeds.

**Data structures**:
```python
self._queue:      queue.Queue(maxsize=1_000)   # BedState results — low volume
self._tick_queue: queue.Queue(maxsize=50_000)  # chart ticks — high volume
# client registry: client_id → {"ws": WebSocket, "focused_bed_id": str | None}
self._clients: dict[str, dict]
self._last_ward_t: dict[str, float]  # last emitted ward tick time per bed
```

**`push_chart_tick(bed_id, ...)`** — called from event loop in `on_sample()`:
```python
self._tick_queue.put_nowait({"bed_id": ..., "fhr": ..., "uc": ..., "t": ...})
```

**`push(state: BedState)`** — called from worker threads:
```python
self._queue.put_nowait(dataclasses.asdict(state))
```

**Focus tracking** (Ruba 2 — ward/detail split):
- `set_focused_bed(client_id, bed_id)` — client opened DetailView; receives full-rate ticks for that bed.
- `clear_focused_bed(client_id)` — client returned to WardView.
- Triggered by `{"type": "focus", "bed_id": "..."}` / `{"type": "unfocus"}` messages from the browser.

**Drain loop** (asyncio task):
```python
async def _drain_loop(self) -> None:
    while self._running:
        # 1. Drain states (max 128)
        bed_states = [self._queue.get_nowait() for _ in range(128) or ...]

        # 2. Drain ticks (max 4096); ward-downsample to ≤ 4 Hz per bed
        ticks_by_bed: dict[str, list] = {}
        ward_ticks: list = []
        for tick in ...:
            ticks_by_bed[tick["bed_id"]].append(tick)
            if tick["t"] - self._last_ward_t.get(bid, -999) >= 0.25:
                ward_ticks.append(tick)
                self._last_ward_t[bid] = tick["t"]

        # 3. Per-client message (different detail ticks per focused bed)
        for client_id, info in self._clients.items():
            focused = info["focused_bed_id"]
            msg = {
                "type": "batch_update",
                "updates": bed_states,
                "ward_chart_ticks": ward_ticks,          # ≤ 4 Hz, all beds
                "chart_ticks": ticks_by_bed.get(focused, []),  # full rate, focused bed only
            }
            await self._send_one(client_id, info["ws"], json.dumps(msg))

        await asyncio.sleep(0.05)
```

**Key property**: `_tick_queue` and `_queue` are independent — a full AI inference backlog cannot drop or delay chart ticks, and vice versa. Heartbeat (`{"type":"heartbeat"}` every 5s) still uses `_send_to_all`.

**Why concurrent sends matter**: With sequential sends, one slow or stuck WebSocket client blocks delivery to all other clients. `asyncio.gather()` with `return_exceptions=True` ensures all sends proceed concurrently; a failed or slow client is automatically unregistered and cannot delay others.

**WebSocket message format (batch_update)**:
```json
{
  "type": "batch_update",
  "timestamp": 1700000000.0,
  "updates": [
    {
      "bed_id": "bed_01",
      "risk_score": 0.72,
      "alert": false,
      "fhr_latest": [142.1, 141.8, ...],
      "uc_latest": [12.5, 13.0, ...],
      "baseline_bpm": 140.0,
      "...": "...all BedState fields..."
    }
  ],
  "chart_ticks": [
    { "bed_id": "bed_01", "fhr": 142.1, "uc": 12.5, "t": 1234.75 },
    { "bed_id": "bed_02", "fhr": 135.3, "uc": 8.2,  "t": 1234.75 }
  ]
}
```

**Timing implications**:
- In steady state at speed 1×: the drain loop fires every 50ms. In that window, 4 beds × 0.25s / 0.05s ≈ 0 or 1 ticks per bed arrive per drain. Each drain delivers ~4–16 chart ticks in one WS message.
- `heartbeat` messages are sent separately on a 5-second interval.

**`initial_state` message** — sent to a new WebSocket client on connect:
```json
{
  "type": "initial_state",
  "beds": [ "...array of BedUpdate (latest BedState snapshot for each bed)..." ]
}
```

---

### 2.5 WebSocket Endpoint (`api/routers/websocket.py`)

```
GET /ws/stream
```

- Upgrades to WebSocket.
- Calls `broadcaster.register(ws)` → websocket is added to `_clients` dict.
- Sends `initial_state` with current snapshot of all beds.
- Enters a receive loop: awaits `ws.receive_text()` (client messages are ignored; loop is just for disconnect detection).
- On disconnect: calls `broadcaster.unregister(ws)`.

---

### 2.6 REST API Overview

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/simulation/start` | Start replay with bed/recording config + speed |
| POST | `/api/simulation/stop` | Stop replay |
| POST | `/api/simulation/speed` | Change replay speed mid-run |
| GET  | `/api/simulation/status` | Current run state |
| GET  | `/api/beds` | List all beds (current BedState snapshot) |
| GET  | `/api/beds/{bed_id}` | Single bed state |
| POST | `/api/beds/{bed_id}/recording` | Hot-swap recording mid-stream |
| GET  | `/api/system/health` | Health check |
| GET  | `/api/system/recordings` | List available recording IDs |
| POST | `/api/god-mode/enable` | Enable God Mode (requires PIN) |
| POST | `/api/god-mode/inject` | Inject a pathology event (requires PIN) |
| DELETE | `/api/god-mode/events/{event_id}` | End an injected event |
| GET  | `/api/god-mode/events` | List active events for a bed |
| DELETE | `/api/god-mode/clear/{bed_id}` | Clear all events for a bed |
| GET  | `/api/god-mode/status` | God Mode enabled/disabled status |

All endpoints are prefixed with `/api`. The `god-mode` endpoints require `X-God-Mode-Pin` header (enforced by `GodModeGuard` middleware).

---

### 2.7 FastAPI App + Lifespan (`api/main.py`)

**Startup sequence** (via `@asynccontextmanager` lifespan):
1. Load `artifacts/production_config.json`.
2. Load model weights once via `model_loader.py` (creates 5 × PatchTST models).
3. Instantiate `AsyncBroadcaster`.
4. Instantiate `PipelineManager(broadcaster, models, ...)`.
5. Instantiate `ReplayEngine` with `manager.on_sample` as callback.
6. Inject all three into `app.state` (accessible via `request.app.state`).
7. Start broadcaster drain + heartbeat loop as an asyncio task.
8. Start `ReplayEngine.run()` as an asyncio task (if `auto_start` is set in config).
9. `yield` — server is alive.
10. On shutdown: cancel all tasks, executor shutdown.

**Dependency injection** (`api/dependencies.py`):
```python
def get_broadcaster(request: Request) -> AsyncBroadcaster:
    return request.app.state.broadcaster

def get_manager(request: Request) -> PipelineManager:
    return request.app.state.manager

def get_engine(request: Request) -> ReplayEngine:
    return request.app.state.engine
```

**CORS**: configured to allow `http://localhost:5173` (Vite dev) and the production origin.

---

## 3. Two Separate Data Flows

This section is critical for understanding the chart smoothness design.

### Flow A: Inference / Clinical State (slow, rich)

```
sample N (every sample) → on_new_sample()
  → if (N - offset) % 40 == 0 AND N >= 1800:
      run PatchTST → BedState
      → broadcaster.push(state)
      → drain loop (≤50ms later) → batch_update.updates[]
      → websocket → useBedStream → updateFromWebSocket()
      → Zustand bedStore.beds[bed_id]
      → React re-render (WardView risk score, DetailView panels)
```

- Frequency: every 40 samples = **every 10 seconds** (staggered per bed — see Fix 10).
- Latency: up to 200ms PatchTST + up to 50ms drain = **up to 250ms**.
- Content: full clinical state — risk score, all features, `fhr_latest`/`uc_latest` (last 40 BPM values), alert flag.
- Side effects: triggers `playAlertTone()` if alert transitions false → true.

### Flow B: Chart Ticks (fast, raw)

```
sample N (every sample)
  → on_sample() on event loop:
      increment _sample_counters[bed_id]
      denormalize → fhr_bpm, uc_mmhg
      broadcaster.push_chart_tick()  ← _tick_queue
  → drain loop (≤50ms later) → batch_update.ward_chart_ticks[] (all clients)
                              → batch_update.chart_ticks[]      (focused client only)
  → websocket → useBedStream:
      ward_chart_ticks → chartUpdateBus.publishWard() → Sparkline RAF loop
      chart_ticks      → chartUpdateBus.publish()     → useCTGChart RAF flush
```

- Frequency: **every sample = 4 Hz** (at speed 1×, configured via `SENTINEL_DEFAULT_REPLAY_SPEED`).
- Latency: up to 50ms drain = **~50ms** (no inference overhead because chart tick is pushed before `executor.submit`).
- Rendering: Sparkline uses `requestAnimationFrame` with dirty flag (1 canvas repaint/frame max). useCTGChart flushes pending ticks in a single RAF callback (1 chart repaint/frame max).
- Side effects: no React render cycle triggered.

### Why decoupled?

Chart ticks are pushed in `on_sample()` on the event loop **before** the inference task is submitted to the thread pool. This means AI latency (50–200ms per PatchTST run) has zero impact on chart smoothness. The old architecture pushed chart ticks from the worker thread after `on_new_sample()`, so heavy inference loads delayed the waveform.

### Timing: drain batching causes burst delivery

The drain loop fires every 50ms. At 1× with 4 beds: ~1 tick per bed arrives per drain cycle. The frontend RAF loops smooth this into a consistent 60fps visual update rate regardless of tick burst timing.

---

## 4. Frontend — Data Pipeline

### 4.1 WebSocket Client (`wsClient.ts`)

**Purpose**: Singleton `WebSocket` wrapper with reconnection logic. Decouples connection management from React component lifecycle.

**Key behavior**:
- Exponential backoff reconnect: 1s, 2s, 4s... up to 30s max.
- `onMessage(handler)` — register a raw string message handler. Returns unsubscribe function.
- `onStatus(handler)` — register a `connected: boolean` handler.
- `connect(url)` — idempotent; will not open a second socket if already connected.
- `disconnect()` — closes socket and cancels reconnect timer.
- `send(data: string)` — sends a raw string to the server. No-op if not connected. Used by `DetailView` to send `focus`/`unfocus` messages.

**Note**: the singleton pattern means all React components share one socket. If `useBedStream` unmounts and remounts (e.g. during strict mode double-invocation), `disconnect()` is called in the cleanup, which prevents reconnect loops.

---

### 4.2 useBedStream Hook

**Purpose**: Mounts once at the app root (`App.tsx`). Routes all WebSocket messages to the right consumers.

**Mount lifecycle**:
```typescript
useEffect(() => {
    const unsubStatus = wsClient.onStatus(setConnected)
    const unsubMsg = wsClient.onMessage((raw) => { ... })
    wsClient.connect(url)
    return () => { unsubStatus(); unsubMsg(); wsClient.disconnect() }
}, [])  // mount-once
```

**Message routing**:
```typescript
if (msg.type === 'batch_update') {
    // Inference updates → Zustand store
    for (const u of msg.updates) {
        updateFromWebSocket(u)           // → bedStore
    }
    // Ward ticks (downsampled ≤ 4 Hz, all beds) → WARD channel
    for (const tick of msg.ward_chart_ticks ?? []) {
        chartUpdateBus.publishWard(tick.bed_id, tick.fhr, tick.uc, tick.t)
    }
    // Detail ticks (full-rate, focused bed only) → DETAIL channel
    // Large reconnect bursts are chunked via setTimeout to avoid monopolising the main thread.
    for (const tick of msg.chart_ticks ?? []) {
        chartUpdateBus.publish(tick.bed_id, [tick.fhr], [tick.uc], tick.t)
    }
} else if (msg.type === 'initial_state') {
    initializeFromSnapshot(msg.beds)    // → bedStore + chartUpdateBus (both channels)
} else if (msg.type === 'heartbeat') {
    setHeartbeat(msg.ts)
}
```

**Ward vs. detail split**: `ward_chart_ticks` arrive for all beds at ≤ 4 Hz and feed `Sparkline` via the WARD channel. `chart_ticks` arrive only for the focused bed at full rate and feed `useCTGChart` via the DETAIL channel. Clients that have no focused bed receive an empty `chart_ticks` list.

---

### 4.3 Zustand Store (`bedStore.ts`)

**Purpose**: Single source of truth for all per-bed inference data. Used by WardView (risk scores, alert badges) and DetailView (clinical panels, risk trend).

**Shape**:
```typescript
interface BedStore {
    beds: Map<string, BedData>
    connected: boolean
    lastHeartbeat: number
    updateFromWebSocket(update: BedUpdate): void
    initializeFromSnapshot(updates: BedUpdate[]): void
    setConnected(v: boolean): void
    setHeartbeat(ts: number): void
    reset(): void
}
```

**`BedData` per bed** (key fields):
```typescript
interface BedData {
    bedId: string
    recordingId: string
    riskScore: number               // 0.0–1.0
    alert: boolean
    fhrRing: RingBuffer<number>     // last 2400 BPM values (10 min @ 4 Hz)
    ucRing: RingBuffer<number>      // last 2400 mmHg values (10 min @ 4 Hz)
    riskHistory: RingBuffer<{t,v}>  // last 600 risk scores (60 min @ 6s each)
    // ...all clinical features...
    lastUpdate: number              // Unix seconds; for stale detection
}
```

**`updateFromWebSocket` — referential equality optimization**:
```typescript
updateFromWebSocket: (update: BedUpdate) => {
    set(state => {
        const existing = state.beds.get(update.bed_id)
        const updated = applyUpdate(existing, update)
        // Only create a new Map if something visible to WardView changed.
        // This prevents unnecessary re-renders when only ring buffers update.
        if (existing
            && existing.riskScore === updated.riskScore
            && existing.alert === updated.alert
            && existing.warmup === updated.warmup
            && existing.sampleCount === updated.sampleCount) {
            state.beds.set(update.bed_id, updated)
            return state  // same reference → no re-render triggered
        }
        const next = new Map(state.beds)
        next.set(update.bed_id, updated)
        return { beds: next }
    })
},
```

**Why this matters**: Zustand triggers re-renders when the return value of `set()` is a new object reference. Without this optimization, every 6-second inference update (even if risk score didn't change) would create `new Map(state.beds)` → all Zustand subscribers re-render → WardView re-renders all BedCards. With the optimization, re-renders only happen when visible fields actually change.

**Note**: `fhrRing`/`ucRing` in bedStore are **NOT** used for the CTG chart. They are maintained for potential future use. The CTG chart uses `chartUpdateBus` which receives ticks at 4 Hz via Flow B.

---

### 4.4 chartUpdateBus (`chartUpdateBus.ts`)

**Purpose**: Singleton pub/sub bus + rolling buffers for chart ticks. Two independent channels bypass Zustand entirely, avoiding React re-renders on every tick.

**Two channels**:

| Channel | Method | Buffer | Subscriber | Used by |
|---------|--------|--------|------------|---------|
| DETAIL | `publish` / `subscribe` / `getHistory` | `RingBuffer(4800)` — 20 min × 4 Hz | `useCTGChart` | DetailView full chart |
| WARD | `publishWard` / `subscribeWard` / `getWardHistory` | `RingBuffer(120)` — ~30 s at 4 Hz | `Sparkline` | BedCard mini-strip |

**O(1) push via RingBuffer**: both channels use `RingBuffer<TickRecord>` from `ringBuffer.ts`. Unlike the previous `TickRecord[] + slice()` approach, push is always O(1) with no allocation on overflow.

**`publish(bedId, fhrVals, ucVals, tStart)`**: pushes full-rate ticks from the detail stream (focused bed). Delivers immediately to the subscriber (if any), then stores in buffer.

**`publishWard(bedId, fhr, uc, t)`**: pushes a single downsampled ward tick (≤ 4 Hz). Used by `useBedStream` to feed `ward_chart_ticks` from the WebSocket message.

**`subscribe(bedId, cb)`** / **`subscribeWard(bedId, cb)`**: one subscriber per channel per bedId. Does NOT replay history — caller must call `getHistory()` / `getWardHistory()` on mount.

**`getHistory(bedId)`** / **`getWardHistory(bedId)`**: returns `HistorySnapshot | null`. Called on chart/sparkline mount to seed initial data.

**Seeding on reconnect**: `bedStore.initializeFromSnapshot()` calls `chartUpdateBus.publish()` and `chartUpdateBus.publishWard()` for each bed in the initial snapshot, so charts and sparklines show context immediately after a page refresh.

---

### 4.5 RingBuffer (`ringBuffer.ts`)

**Purpose**: Fixed-capacity circular buffer with O(1) push, O(N) snapshot.

```typescript
class RingBuffer<T> {
    private buf: T[]
    private head: number    // next write position
    private _size: number   // current fill level

    push(item: T): void     // O(1), overwrites oldest when full
    toArray(): T[]          // O(N), returns items oldest-to-newest
    get length(): number    // current fill level
    get capacity(): number  // max capacity
}
```

Used in: `bedStore.ts` for `fhrRing`, `ucRing`, `riskHistory`; and `chartUpdateBus.ts` for both DETAIL and WARD tick buffers.

---

### 4.6 useCTGChart Hook

**Purpose**: Creates and manages a `lightweight-charts` IChartApi instance for the **full-size detail chart only**. Mini-strips in BedCard use `Sparkline` instead. Subscribed to the DETAIL channel of `chartUpdateBus`.

**Signature**:
```typescript
function useCTGChart(
    containerRef: RefObject<HTMLElement | null>,
    bedId: string,
    activeEvents?: EventAnnotation[],
    baselineBpm?: number,
): void
```

**Effect 1 — Chart creation** (`deps: [containerRef]`):
- Creates `IChartApi` with full axes, grid, time scale, crosshair.
- Adds FHR series (right price scale, `#111827`) and UC series (left price scale, `#6b7280`).
- Attaches `ResizeObserver`. Returns cleanup: `chart.remove()`.
- No `compact` variant — `Sparkline` (canvas-based) handles all mini-strips.

**Effect 2 — Deferred history + RAF-batched subscription** (`deps: [bedId]`):

```typescript
useEffect(() => {
    // Defer history setData to next frame — DetailView shell renders first
    requestAnimationFrame(() => {
        fhrS.setData(hist.fhrVals.map(...))  // full history in one pass
        ucS.setData(hist.ucVals.map(...))

        // Subscribe AFTER setData: live ticks always have t > history end
        unsubLive = chartUpdateBus.subscribe(bedId, (fhrVals, ucVals, tStart) => {
            // Accumulate in pendingFhr / pendingUc
            if (rafHandle === null) rafHandle = requestAnimationFrame(flush)
        })
    })
```

**RAF batching**: incoming live ticks are buffered in `pendingFhr` / `pendingUc`; a single `requestAnimationFrame` drains the buffer with one chart repaint per display frame. This replaces the previous pattern of calling `series.update()` synchronously on every tick, which caused up to 640 `update()` calls/second at 10× with 16 beds.

**Deferred history**: `setData()` is scheduled via `requestAnimationFrame` so DetailView's header, risk gauge, and controls paint before the potentially heavy history load. The subscription is opened INSIDE the RAF callback (after `setData`) to guarantee tick ordering.

```typescript
// Old pattern (removed):
    // 1. Load history FIRST (synchronously, before subscribing)
    //    Full mode only — compact charts skip history (no visual value at 112px height)
    if (!compact && fhr && uc) {
        const hist = chartUpdateBus.getHistory(bedId)
        if (hist) {
            const step = 0.25
            try {
                fhr.setData(hist.fhrVals.map((v, i) => ({ time: (hist.tStart + i * step) as Time, value: v })))
                uc.setData(hist.ucVals.map((v, i) => ({ time: (hist.tStart + i * step) as Time, value: v })))
            } catch { /* ignore if chart was removed */ }
        }
    }

    // 2. THEN subscribe for live ticks — all future ticks have t > history end
    const unsubscribe = chartUpdateBus.subscribe(bedId, (fhrVals, ucVals, tStart) => {
        const fhrS = fhrSeries.current
        const ucS  = ucSeries.current
        if (!fhrS || !ucS) return

        const step = 0.25
        for (let i = 0; i < fhrVals.length; i++) {
            const t = (tStart + i * step) as Time
            try { fhrS.update({ time: t, value: fhrVals[i] }) } catch { /* ignore out-of-order */ }
        }
        for (let i = 0; i < ucVals.length; i++) {
            const t = (tStart + i * step) as Time
            try { ucS.update({ time: t, value: ucVals[i] }) } catch { /* ignore out-of-order */ }
        }
    })

    return unsubscribe
}, [bedId, compact])
```

**Critical ordering — history BEFORE subscribe**:
Previously, the hook subscribed first (to receive live ticks immediately) and deferred `setData()` to a double-`requestAnimationFrame` callback (~30ms later). This caused a race: live ticks arriving via `update()` in those 30ms had timestamps beyond the history's end; when `setData()` fired, it replaced the entire series including those live points, creating a visible gap/jump in the chart.

The fix: call `setData(history)` synchronously inside the effect (before subscribing). This is ~5ms for 4800 points. After `setData()` completes, `subscribe()` is called — all subsequent `update()` calls have `t > history.end`, so they append correctly without any race.

**`series.update()` vs `series.setData()`**:
- `update(point)`: appends one point. Requires `point.time > last_point_time` — drops the point silently if not.
- `setData(array)`: replaces entire dataset. Used only for history load on mount.

**Effect 3 — Baseline price line** (`deps: [baselineBpm, compact]`):
Draws a dashed horizontal line on the FHR series at `baselineBpm`. Skipped in compact mode.

**Effect 4 — Event markers** (`deps: [activeEvents, compact]`):
Sets God Mode injection event markers on the FHR series (arrow-down at start, arrow-up at end). Skipped in compact mode.

---

## 5. Frontend — Component Tree

### 5.1 App.tsx and Routing

```typescript
function App() {
    useBedStream()    // mount WebSocket — runs globally for app lifetime
    const selectedBedId    = useUIStore(s => s.selectedBedId)
    const setSelectedBedId = useUIStore(s => s.setSelectedBedId)
    return (
        <>
            {/* Modal overlay — WardView stays mounted underneath */}
            {selectedBedId && (
                <div className="fixed inset-0 z-40 bg-black/40" onClick={() => setSelectedBedId(null)}>
                    <div onClick={e => e.stopPropagation()}>
                        <DetailView bedId={selectedBedId} onClose={() => setSelectedBedId(null)} />
                    </div>
                </div>
            )}
            <Routes>
                <Route path="/" element={<WardView />} />
            </Routes>
        </>
    )
}
```

There is only one route (`/`). Clicking a bed card opens `DetailView` in a floating modal overlay — `WardView` is never unmounted, so all 16 mini CTG charts keep streaming without interruption. The `/bed/:id` route has been removed. `uiStore.selectedBedId` drives modal visibility.

---

### 5.2 WardView

```typescript
export const WardView: React.FC = () => {
    const beds        = useBedStore(s => s.beds)
    const gridColumns = useUIStore(s => s.gridColumns)
    const navigate    = useNavigate()

    // useMemo: sorted array only recomputed when beds Map reference changes
    const sorted = useMemo(
        () => Array.from(beds.values()).sort((a, b) => b.riskScore - a.riskScore),
        [beds],
    )

    // useCallback: stable reference prevents BedCard re-renders from onClick prop change
    const handleClick = useCallback(
        (bedId: string) => setSelectedBedId(bedId),
        [setSelectedBedId],
    )

    return (
        <div className={`grid ${colClass} gap-3 p-4 auto-rows-fr`}>
            {sorted.map(bed => (
                <BedCard key={bed.bedId} bed={bed} onClick={handleClick} />
            ))}
        </div>
    )
}
```

- `useMemo` for sorting: without it, every parent re-render recreates the sorted array unnecessarily, causing all BedCards to re-render even if their data didn't change.
- `useCallback` for `handleClick`: without it, a new function reference on every render invalidates `React.memo` on BedCard, forcing re-renders even when `bed` data is unchanged.

---

### 5.3 BedCard

```typescript
export const BedCard: React.FC<Props> = React.memo(({ bed, onClick }) => {
    return (
        <button onClick={handleClick} ...>
            {/* Risk score + risk bar + recording ID */}
            {/* Mini CTG strip — canvas-based, not lightweight-charts */}
            <div className="w-full h-28 mt-1 rounded overflow-hidden">
                <Sparkline bedId={bed.bedId} />
            </div>
        </button>
    )
})
```

- `React.memo`: only re-renders when `bed` or `onClick` prop changes.
- **`Sparkline`** (not `CTGChart`): canvas-based component that subscribes to the WARD channel of `chartUpdateBus`. Draws FHR (dark, top half) and UC (grey, bottom half) via a `requestAnimationFrame` loop with a dirty flag — only redraws when new ward ticks arrive.
- With 16 beds, there are 16 `<canvas>` elements active simultaneously. Each is a plain 2D canvas with ~240 data points — negligible GPU/CPU cost compared to the previous 16 lightweight-charts instances.
- Re-renders of BedCard do NOT affect the canvas — chart data is managed imperatively via `chartUpdateBus`.

---

### 5.4 DetailView

```typescript
interface Props {
    bedId?: string    // passed when used as a modal
    onClose?: () => void
}

function DetailView({ bedId: propBedId, onClose }: Props) {
    const { id: routeId } = useParams()
    const id = propBedId ?? routeId       // prop takes precedence over URL

    return (
        <div>
            {/* Back button — calls onClose() in modal mode, Link to "/" in route mode */}
            <CTGChart bedId={id} baselineBpm={bed?.baselineBpm} activeEvents={bed?.activeEvents} />
            {/* Risk gauge, clinical feature panels, alert history, god mode */}
        </div>
    )
}
```

- Navigated via React Router (`/bed/:id`).
- On mount, sends `{"type":"focus","bed_id":"..."}` to the WebSocket server so this client receives full-rate detail ticks for the opened bed.
- On unmount, sends `{"type":"unfocus"}` to return to ward-only ticks.
- `CTGChart` uses deferred `setData()` + RAF-batched live updates (see §4.6).
- `baselineBpm` and `activeEvents` come from Zustand (updated by Flow A every 6s).
- BedCard `Sparkline` components on WardView remain mounted and continue receiving ward ticks while DetailView is open.

---

### 5.5 CTGChart Component

```typescript
interface Props {
    bedId: string
    activeEvents?: EventAnnotation[]
    baselineBpm?: number
}

function CTGChart({ bedId, activeEvents, baselineBpm }: Props) {
    const containerRef = useRef<HTMLDivElement>(null)
    useCTGChart(containerRef, bedId, activeEvents, baselineBpm)

    return (
        <div
            ref={containerRef}
            className="w-full h-72 rounded overflow-hidden bg-white border border-gray-200"
        />
    )
}
```

The component itself is a thin container div — all chart logic is in `useCTGChart`. Height: 112px (`h-28`) in compact mode, 288px (`h-72`) in full mode.

---

## 6. Timing Budget and Latency Stack

### End-to-end latency: sample → pixel

At speed 1×, for a chart tick on bed_01:

| Stage | Time |
|-------|------|
| ReplayEngine fires `callback()` | 0 ms |
| `on_sample()` submits to thread pool | ~0.1 ms |
| Worker thread: denormalize + push_chart_tick | ~0.1 ms |
| `push_chart_tick()` enqueues in `queue.Queue` | ~0.1 ms |
| Drain loop picks up (worst case: full interval) | 0 – 50 ms |
| JSON serialization + concurrent WS send | ~1–2 ms |
| Network (localhost) | ~0.1 ms |
| `onMessage` handler + `chartUpdateBus.publish()` | ~0.1 ms |
| `series.update()` → canvas repaint | ~0.1 ms |
| **Total end-to-end** | **~1 – 52 ms** |

### Flow A latency (inference updates)

| Stage | Time |
|-------|------|
| `on_new_sample()` — ring buffer append | ~0.1 ms |
| Numpy conversion (once) + inference window slice | ~0.5 ms |
| PatchTST ensemble forward pass | ~50–200 ms |
| `_compute_full_state()` — clinical features | ~5–20 ms |
| Drain loop pickup + WS send | 0–50 ms |
| **Total** | **~55–270 ms** (every 6 seconds) |

### Drain interval vs tick rate

```
Backend tick rate:     4 Hz = 250ms period
Drain interval:        50ms
Drain cycles per tick: 5

Expected: 4 drain cycles with 0 ticks, 1 drain cycle with 1 tick per bed.
Actual: asyncio scheduling jitter causes some variation, but average throughput is exact.
```

### High-speed warmup timing

At speed 15×: 1800 samples ÷ (15 samples/0.25s × 4 beds ÷ 4 beds) = 30 seconds real time to complete warmup. All 4 beds then produce inference results simultaneously.

---

## 7. God Mode System

**Purpose**: Allows authorized users (clinicians/testers) to inject synthetic pathology events into one or more beds to test the alerting system.

**Auth**: `X-God-Mode-Pin` header, validated by `GodModeGuard` middleware on all `/api/god-mode/*` routes. PIN is stored in `artifacts/production_config.json`.

**Injection flow**:
1. `POST /api/god-mode/inject` with `{ bed_id, event_type, severity, duration_seconds }`.
2. `GodModeInjector` creates an `InjectionEvent` and registers it for the bed.
3. On subsequent `on_new_sample()` calls for that bed, the `GodModeInjector` overrides feature outputs to simulate the pathology.
4. The `BedState` includes `god_mode_active: true` and `active_events: [...]` when God Mode is active.
5. Frontend shows a visual indicator on `BedCard` and `DetailView` when `godModeActive` is true.
6. Event markers appear on the FHR chart (arrow-down at start, arrow-up at end).

**Event catalog** (`data/god_mode_catalog.json`): defines available event types and their feature override parameters.

**God Mode Guard** (`api/middleware/god_mode_guard.py`):
- Middleware that intercepts all requests to `/api/god-mode/*`.
- If `X-God-Mode-Pin` header is missing or incorrect → 403 Forbidden.
- Does NOT affect other routes.

**Baseline recording tracking** (`PipelineManager._baseline_recordings`):
When `set_beds()` is called, the original `recording_id` for each bed is stored. God Mode's `restore` operation always uses the original baseline, not the currently-playing recording, ensuring correct restoration even after multiple overlapping signal swaps.

---

## 8. Performance Fixes Applied

This section documents all performance issues identified and fixed to make the system production-quality (smooth, non-blocking, reliable under sustained load).

### Fix 1 — ReplayEngine event loop starvation (generator/replay.py)

**Problem**: At high speed multipliers (10–20×), `ticks_this_cycle` could be 10–20 iterations. The inner loop called `self._callback()` for every bed on every tick without yielding, holding the asyncio event loop for the entire burst. The drain loop, heartbeat, and WebSocket sends could not run until the burst completed.

**Fix**: Added `await asyncio.sleep(0)` between ticks (but not after the last tick, since `asyncio.sleep(TICK_INTERVAL)` handles that). This yields to the event loop scheduler between each tick's batch of callbacks, at zero real wall-time cost.

### Fix 2 — Sequential WebSocket sends blocked by slow clients (broadcaster.py)

**Problem**: `_send_to_all()` iterated over clients and awaited each `ws.send_text()` sequentially. A single slow or unresponsive client would block all other sends until its send completed or timed out. With no timeout, a stuck client blocked forever.

**Fix**: Serialize JSON once (`json.dumps(msg)`), then fan out to all clients with `asyncio.gather(*tasks, return_exceptions=True)` where each task uses `asyncio.wait_for(..., timeout=2.0)`. All clients receive their data concurrently; a failed client is unregistered immediately.

### Fix 3 — Redundant numpy array conversion (src/inference/pipeline.py)

**Problem**: `on_new_sample()` converted `deque → numpy` once to extract the inference window, then `_compute_full_state()` converted the same deques to numpy again for clinical feature extraction. At 4 Hz × inference stride, this doubled the numpy allocation cost on every inference tick.

**Fix**: Convert deques to numpy once at the top of `on_new_sample()`. Pass `fhr_full` and `uc_full` as parameters to `_compute_full_state(fhr_arr, uc_arr)`, eliminating the second conversion.

### Fix 4 — `_window_scores` unbounded growth (src/inference/pipeline.py)

**Problem**: `_window_scores` accumulated `(start_sample, probability)` tuples indefinitely. After 10+ hours of operation, the list could contain thousands of entries, causing O(N) memory and scan overhead.

**Fix**: After each append, cap the list to `_WINDOW_SCORE_MAX = 300` entries (≈30 minutes of inference history): `self._window_scores = self._window_scores[-_WINDOW_SCORE_MAX:]`.

### Fix 5 — Backpressure: unbounded ThreadPoolExecutor queue (pipeline_manager.py)

**Problem**: At high speeds (15–20×) with multiple beds, `on_sample()` could submit hundreds of tasks to the `ThreadPoolExecutor` queue per second. The executor's internal queue grew without bound, consuming memory and causing head-of-line blocking (early tasks delayed by later tasks queued behind them).

**Fix**: Track `_pending[bed_id]` with a `defaultdict(int)`. If pending tasks for a bed reach 50, drop the sample silently. The limit of 50 is high enough to allow normal warmup and steady-state operation, while preventing extreme queue growth at 20× speed with 16 beds.

### Fix 6 — Zustand Map recreation on every inference update (bedStore.ts)

**Problem**: `updateFromWebSocket()` always called `new Map(state.beds)`, creating a new Map reference on every 6-second inference update. Zustand uses shallow reference comparison: a new Map always triggers re-renders in all subscribers, even if no visible data changed. WardView re-rendered all BedCards every 6 seconds per bed regardless of actual changes.

**Fix**: Compare key visible fields (`riskScore`, `alert`, `warmup`, `sampleCount`) before creating a new Map. If unchanged, mutate the existing Map in place and return the same state reference — Zustand sees no change and triggers no re-renders.

### Fix 7 — Unstable onClick prop invalidating React.memo (WardView.tsx / BedCard.tsx)

**Problem**: WardView passed `onClick={() => navigate(\`/bed/${bed.bedId}\`)}` as a prop to BedCard. A new arrow function is created on every render, so `React.memo` on BedCard always sees a new `onClick` reference and re-renders every card on every parent render.

**Fix**: WardView uses `useCallback((bedId) => navigate(\`/bed/${bedId}\`), [navigate])` for a stable `handleClick` reference. BedCard's prop type changed from `() => void` to `(bedId: string) => void`. BedCard wraps its internal handler with `useCallback(() => onClick(bed.bedId), [onClick, bed.bedId])`.

### Fix 8 — setData() race with live ticks on DetailView mount (useCTGChart.ts)

**Problem**: The hook previously subscribed for live ticks first, then deferred `setData(history)`. During the delay, live ticks arrived with timestamps beyond history range; when `setData()` fired it replaced them, causing a visible gap.

**Fix (Ruba 4)**: Both history load and subscription are deferred together to `requestAnimationFrame`. Inside the RAF callback, `setData()` runs first, then the subscription is opened — so all live ticks have `t > history.end` and append cleanly.

### Fix 9 — O(N) buffer trimming in chartUpdateBus.ts

**Problem**: Buffer trimming used `buf.splice(0, N)` (O(N) shift) and `buf.slice(-MAX)` with hysteresis. At 4 Hz × 16 beds this caused frequent array allocations.

**Fix (Ruba 5)**: Replaced `TickRecord[]` with `RingBuffer<TickRecord>` for both DETAIL (capacity 4800) and WARD (capacity 120) channels. `push()` is O(1) with no allocation on overflow. `toArray()` is called only in `getHistory()` / `getWardHistory()` on chart mount — not on every tick.

### Fix 10 — 640 series.update() calls/second at 10× (useCTGChart.ts)

**Problem**: Each chart tick called `series.update()` synchronously in the WebSocket message handler. At 10× speed with 16 beds: 16 × 40 Hz × 2 series = 1280 `update()` calls/second on the main thread.

**Fix (Ruba 4)**: Live ticks are buffered in `pendingFhr`/`pendingUc`. A single `requestAnimationFrame` drains the buffer in one pass — at most 1 repaint per display frame per chart, regardless of tick rate.

### Fix 11 — 16 lightweight-charts instances on WardView (BedCard.tsx / Sparkline.tsx)

**Problem**: Each `BedCard` mounted a full `lightweight-charts` instance (canvas with axes, grid, labels) for a 112px mini-strip. 16 beds = 16 active chart instances with WebGL/canvas compositing overhead.

**Fix (Ruba 3)**: Replaced `CTGChart compact` with `Sparkline` — a raw `<canvas>` with a hand-drawn 2D line. No chart library, no axes. RAF loop redraws only when `dirty = true`. 16 canvases with ~240 data points each is negligible CPU/GPU.

### Fix 12 — Chart ticks delayed by AI inference (pipeline_manager.py)

**Problem**: `push_chart_tick()` was called inside `_process_and_broadcast()` in the thread pool, after `pipeline.on_new_sample()`. During heavy inference (50–200ms), chart ticks were delayed.

**Fix (Ruba 1)**: `push_chart_tick()` is now called in `on_sample()` on the event loop, before `executor.submit()`. AI inference latency has zero impact on waveform delivery.

### Fix 13 — All clients receiving full-rate ticks for all beds (broadcaster.py)

**Problem**: All WebSocket clients received chart ticks for every bed at full rate, even beds not currently being viewed. At 10× with 16 beds, each client received 640 ticks/s even if no DetailView was open.

**Fix (Ruba 2)**: Ward downsampling (≤ 4 Hz) for `ward_chart_ticks` sent to all clients. Full-rate `chart_ticks` sent only to the client whose `focused_bed_id` matches. Clients send `{"type":"focus","bed_id":"..."}` when opening DetailView and `{"type":"unfocus"}` on close.

### Fix 10 — CPU saturation at 16 beds (pipeline_manager.py + pipeline.py)

**Problem**: Endurance test (35 min, 16 beds) showed 54–81% CPU once all 16 beds entered the inference phase. Root cause: all 16 beds hit their 1800-sample warmup threshold at exactly the same tick and then fired inference simultaneously every 24 samples (6s). With `max_workers=4`, the 4 threads were continuously saturated.

**Fix — two changes:**
1. **Inference staggering**: `SentinelRealtime` accepts `inference_offset: int`. Inference fires when `(sample_count - offset) % stride == 0` instead of `sample_count % stride == 0`. `PipelineManager.set_beds()` computes `offset = (i * stride) // n_beds` for each bed index `i`, spreading N beds evenly across one stride window. With 16 beds, at most 1–2 beds fire inference per sample tick instead of all 16 simultaneously.
2. **Wider stride + more workers**: `_INFERENCE_STRIDE` increased from 24 (6s) to 40 (10s), reducing inference throughput from 2.7/s to 1.6/s. `max_workers` raised from 4 to 8.

**What is NOT staggered**: Chart ticks (Flow B) are still pushed unconditionally every sample for every bed — the waveforms update simultaneously at 4 Hz without any staggering.

---

## 9. Data Formats and Normalization

### .npy file format
```
Shape: (2, T) — float32
Channel 0: FHR normalized = (bpm - 50) / 160  → range [0, 1] for bpm in [50, 210]
Channel 1: UC normalized  = mmhg / 100         → range [0, 1] for mmhg in [0, 100]
NaN values: replaced at load time (FHR→0.5, UC→0.0)
```

### Denormalization (in PipelineManager)
```python
fhr_bpm  = fhr_norm * 160.0 + 50.0    # chart display BPM
uc_mmhg  = uc_norm * 100.0             # chart display mmHg
```

### WebSocket chart_tick
```json
{ "bed_id": "bed_01", "fhr": 142.5, "uc": 12.3, "t": 1234.75 }
```
- `t`: seconds elapsed since start of recording playback (computed as `(sample_count + 1) / 4.0`).
- `fhr`: BPM (float, 1 decimal).
- `uc`: mmHg (float, 1 decimal).

### BedUpdate (inference, every 10s)
- `fhr_latest`: array of 40 BPM values (the 40 samples from the last inference window).
- `uc_latest`: array of 40 mmHg values.
- These are pushed into `bedStore.fhrRing`/`ucRing` (size 2400 = 10min × 4Hz).
- **Not used for the chart** — chart uses `chart_ticks` from Flow B.

---

## 10. File Map — Every Source File Explained

### Backend

| File | Purpose |
|------|---------|
| `api/main.py` | FastAPI app factory, lifespan context manager, startup/shutdown |
| `api/config.py` | Config loading from `artifacts/production_config.json` |
| `api/dependencies.py` | FastAPI `Depends()` helpers: get_broadcaster, get_manager, get_engine |
| `api/logging_config.py` | Logging setup (file + console handlers, sentinel.audit logger) |
| `api/middleware/god_mode_guard.py` | Middleware: checks X-God-Mode-Pin on /api/god-mode/* routes |
| `api/models/schemas.py` | Pydantic models: BedUpdate, BatchUpdateMessage, ChartTick, etc. |
| `api/routers/beds.py` | GET /api/beds, GET /api/beds/{bed_id}, POST /api/beds/{bed_id}/recording |
| `api/routers/god_mode.py` | God Mode CRUD endpoints |
| `api/routers/recordings.py` | GET /api/system/recordings |
| `api/routers/simulation.py` | start/stop/speed/status endpoints for ReplayEngine |
| `api/routers/system.py` | GET /api/system/health |
| `api/routers/websocket.py` | WebSocket upgrade + register/unregister with broadcaster |
| `api/services/alert_history.py` | Persist alert events to `data/alert_log.jsonl` |
| `api/services/broadcaster.py` | Thread-safe queue → concurrent async WebSocket push; drain loop |
| `api/services/model_loader.py` | Load PatchTST ensemble once, shared across pipelines |
| `api/services/note_store.py` | Clinical notes per bed (in-memory) |
| `api/services/pipeline_manager.py` | ThreadPoolExecutor with backpressure; routes samples to SentinelRealtime; push chart ticks |
| `generator/replay.py` | ReplayEngine (asyncio 4 Hz loop with event-loop yields) + RecordingReplay (infinite .npy reader) |
| `src/inference/pipeline.py` | SentinelRealtime: ring buffers, single-conversion numpy, PatchTST inference, BedState; public bed_id property |
| `src/model/patchtst.py` | PatchTST model architecture |
| `src/model/heads.py` | ClassificationHead attached to PatchTST |
| `src/god_mode/injector.py` | GodModeInjector: feature override logic |
| `src/god_mode/types.py` | EventType enum, InjectionEvent dataclass |
| `src/rules/` | Clinical feature extraction (baseline, variability, decelerations, etc.) |
| `artifacts/production_config.json` | Weight paths, alert thresholds, god mode PIN |

### Frontend

| File | Purpose |
|------|---------|
| `frontend/src/App.tsx` | Root component: WS stream, modal overlay for DetailView, single `/` route |
| `frontend/src/types.ts` | TypeScript interfaces: BedUpdate, ChartTick, WSMessage, EventAnnotation |
| `frontend/src/services/wsClient.ts` | Singleton WebSocket with exponential backoff reconnect |
| `frontend/src/hooks/useBedStream.ts` | WebSocket message router: bedStore + chartUpdateBus (ward + detail channels) |
| `frontend/src/hooks/useCTGChart.ts` | lightweight-charts lifecycle for detail chart: deferred history, RAF-batched live ticks |
| `frontend/src/stores/bedStore.ts` | Zustand store with referential equality optimization; `initializeFromSnapshot` seeds chartUpdateBus |
| `frontend/src/utils/chartUpdateBus.ts` | Singleton pub/sub with two RingBuffer channels: DETAIL (4800) + WARD (120) |
| `frontend/src/utils/ringBuffer.ts` | Generic O(1) ring buffer — used by bedStore and chartUpdateBus |
| `frontend/src/utils/alertSound.ts` | Play alert tone on risk threshold breach |
| `frontend/src/components/ward/WardView.tsx` | Ward grid with useMemo sort + useCallback; navigation to DetailView |
| `frontend/src/components/ward/BedCard.tsx` | Single bed tile: risk badge + Sparkline mini-strip; React.memo + useCallback |
| `frontend/src/components/common/Sparkline.tsx` | Canvas-based CTG mini-strip; subscribes to WARD channel; RAF + dirty flag |
| `frontend/src/components/detail/DetailView.tsx` | Full bed view; sends focus/unfocus to WS; renders CTGChart + risk panels |
| `frontend/src/components/detail/CTGChart.tsx` | lightweight-charts container for detail chart only (h-72, full axes) |
| `frontend/src/components/GodModePanel.tsx` | God Mode controls: inject events, set PIN |

---

## 10. Validated Performance — Endurance Test Results

**Test:** `scripts/perf_test_16beds.py` — 35 minutes, 16 beds, speed 1x
**Date:** 2026-03-08

### Results

| Metric | Result | Threshold | Status |
|--------|--------|-----------|--------|
| Memory (RSS) | 35–36 MB (flat throughout) | ≤ 1024 MB | **PASS** |
| Memory plateau (after min 30) | +0 MB drift | < 50 MB drift | **PASS** |
| WS lag p99 | max 20 ms | < 200 ms | **PASS** |
| WS reconnections | 0 | 0 | **PASS** |
| CPU (16 beds, inference phase) | 54–81% | ≤ 40% | **FAIL** |

### CPU Analysis

CPU stays at 22–25% during warmup (first 7.5 minutes, no inference). Once all 16 beds hit their 1800-sample warmup threshold simultaneously (T+07:30), CPU jumps to 54–81% and stays there.

**Root cause:** All 16 beds fired inference simultaneously every 6s, saturating `ThreadPoolExecutor(max_workers=4)`.

**What is unaffected:** Memory and WS lag remain excellent throughout. The system is functionally stable — all CTG charts update, all alerts fire, no frames dropped.

**Fix applied (Fix 10):** Inference staggered across beds + stride extended 6s → 10s + max_workers raised 4 → 8. See Section 8 Fix 10 for full details. Re-run endurance test to confirm CPU drops below 40%.

### Memory Stability Confirmation

Ring buffer plateau confirmed:
- `_fhr_ring` and `_uc_ring` each reach `maxlen=7200` at T+30:00
- `_window_scores` deque capped at 300 entries
- RSS flat at 36 MB from T+01 through T+34 — no upward trend, no memory leak

---

*Last updated: 2026-03-08 — reflects codebase state after Phase 8 endurance test, CPU stagger fix (Fix 10), inference stride 10s, max_workers=8, and UI modal refactor.*

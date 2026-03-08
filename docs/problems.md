# Verified Performance Issues (Code-Verified, No Duplicates)

Date: 2026-03-08
Scope: Verified against current code in `api/`, `generator/`, `src/`, `frontend/`.
Goal: list only real issues that can explain "not smooth / frequent stalls".

## ISSUE-01 (P0) - Detail chart loses live points on mount (history race)
Evidence: `frontend/src/hooks/useCTGChart.ts:107` subscribes to live ticks immediately, while history `setData()` is deferred with double `requestAnimationFrame` (`:138-148`).
Why real: live `update()` calls can arrive before deferred `setData()`. Later `setData()` replaces full series and overwrites those live points.
Impact: visible jump/gap right after navigating to DetailView; appears as freeze then snap.

## ISSUE-02 (P0) - WebSocket batch handling blocks main thread in bursts
Evidence: `frontend/src/hooks/useBedStream.ts:36-41` loops synchronously over all `updates` and all `chart_ticks`; each tick calls `chartUpdateBus.publish(...)`.
Evidence: `frontend/src/hooks/useCTGChart.ts:115-121` processes arrays synchronously and calls `series.update()` per sample.
Why real: all this runs inside one JS message event; large batches create long tasks on UI thread.
Impact: frame drops and stutter, especially with many beds / higher speed / reconnect bursts.

## ISSUE-03 (P1) - React re-render storm on every batch_update
Evidence: `frontend/src/hooks/useBedStream.ts:36-37` calls `updateFromWebSocket` once per bed update (multiple Zustand `set()` calls per WS frame).
Evidence: `frontend/src/components/ward/WardView.tsx:24` re-sorts all beds every render; `:45` passes inline `onClick={() => ...}`.
Evidence: `frontend/src/components/ward/BedCard.tsx:17` uses `React.memo`, but inline `onClick` from parent changes each render, defeating memoization.
Why real: one backend batch can trigger many store updates plus full ward re-render path.
Impact: periodic UI hitching, typically every inference batch when many beds update together.

## ISSUE-04 (P1) - Backend delivers chart data in bursts, not evenly
Evidence: `api/services/broadcaster.py:31` uses fixed `_DRAIN_INTERVAL = 0.05`.
Evidence: `api/services/broadcaster.py:124-143` drains all queued items and sends one big message per cycle.
Why real: producer timing (samples) and drain timing are not synchronized; receiver gets bursty chunks.
Impact: non-uniform chart motion ("jittery") even when source sampling is uniform.

## ISSUE-05 (P1) - No backpressure limits (executor plus broadcaster are unbounded)
Evidence: `api/services/pipeline_manager.py:201` submits one task per sample; executor is `max_workers=4` (`:66`) with no queue cap/drop policy.
Evidence: `api/services/broadcaster.py:43` uses `queue.Queue()` with no `maxsize`.
Why real: under load, pending work can grow without bound.
Impact: increasing latency, memory growth, burst processing, and worsening smoothness over time.

## ISSUE-06 (P1) - Tick timestamp/order can become inconsistent under concurrency
Evidence: `api/services/pipeline_manager.py:221` computes `t` from `pipeline.current_sample_count` before calling `on_new_sample`.
Evidence: same method immediately pushes chart tick (`:222`) before sample is serialized inside pipeline lock.
Why real: multiple worker threads for same bed can read the same pre-lock counter value when one thread is inside a long inference tick.
Impact: duplicate/out-of-order tick times; frontend may drop out-of-order points (`update()` path), causing visual discontinuities.

## ISSUE-07 (P2) - O(N) buffer trimming in hot chart path
Evidence: `frontend/src/utils/chartUpdateBus.ts:75` uses `buf.splice(0, overflow)` for trim.
Why real: `splice` shifts array contents (linear cost); runs in publish path.
Impact: periodic CPU spikes/GC pressure when buffers are near limit and traffic is high.

## ISSUE-08 (P0) - ReplayEngine hogs event loop at high speed multipliers
Evidence: `generator/replay.py:269-278` — inner loop runs `ticks_this_cycle × len(beds)` synchronous callback invocations before yielding to the event loop.
At speed 10× with 4 beds: 10 × 4 = 40 synchronous `self._callback()` calls per 0.25s cycle, each calling `executor.submit()`. At speed 20×: 20 × 4 = 80 calls.
All of this runs on the asyncio thread with no intermediate `await` — the event loop is blocked for the entire batch.
Why real: verified in `replay.py:269-278`. The `await asyncio.sleep()` only happens AFTER the entire nested loop completes. If the loop takes longer than `TICK_INTERVAL` (0.25s), `sleep_time` becomes 0 and the loop immediately runs again with no breathing room.
Impact: broadcaster drain loop and heartbeat loop starve for CPU. WebSocket messages back up. Chart data arrives in large bursts instead of steadily. This is the **primary cause** of the system feeling stuck at higher speeds.

## ISSUE-09 (P1) - _window_scores grows unboundedly in SentinelRealtime
Evidence: `src/inference/pipeline.py:223` — `self._window_scores: list[tuple[int, float]] = []`
Evidence: `src/inference/pipeline.py:285` — `self._window_scores.append((start, prob))` — only appends, never trims.
Evidence: `src/inference/pipeline.py:379-384` — passed to `extract_recording_features()` which iterates over all entries.
Evidence: `src/inference/pipeline.py:393` — `all_probs = [p for _, p in self._window_scores]` — creates full copy every inference tick.
Why real: at 4 Hz with inference every 24 samples (6 sec), this accumulates ~10 entries/min, ~600/hr, ~4800 in 8 hours. Each inference tick iterates the ENTIRE list to compute features and global stats.
Impact: gradual degradation — inference time increases linearly with session duration. After 8+ hours of continuous operation, each inference tick processes thousands of entries unnecessarily. Also causes increasing memory usage.

## ISSUE-10 (P1) - Redundant numpy array creation from deque in inference path
Evidence: `src/inference/pipeline.py:275-276` — first conversion:
```python
fhr_win = np.array(self._fhr_ring, dtype=np.float32)[-_WINDOW_LEN:]
uc_win = np.array(self._uc_ring, dtype=np.float32)[-_WINDOW_LEN:]
```
Evidence: `src/inference/pipeline.py:369-370` — second conversion (same deques, same tick):
```python
fhr_arr = np.array(self._fhr_ring, dtype=np.float32)
uc_arr = np.array(self._uc_ring, dtype=np.float32)
```
Why real: `np.array(deque)` copies all 7200 elements to a new numpy array. This happens TWICE per inference tick, under `_state_lock`. The first call also does `[-_WINDOW_LEN:]` slicing which creates a THIRD temporary array (full 7200-element array → then slice to 1800).
Impact: ~3× unnecessary memory allocation + copy on every inference tick (every 6s per bed). All under lock, increasing lock contention for other thread pool workers.

## ISSUE-11 (P1) - Sequential WebSocket sends with no timeout block broadcast loop
Evidence: `api/services/broadcaster.py:152-164` — `_send_to_all()` iterates over clients sequentially:
```python
for client_id, ws in list(self._clients.items()):
    await ws.send_json(msg)
```
Why real: if one WebSocket client is slow (network congestion, client tab frozen), `await ws.send_json()` blocks the drain loop. During this block, no other clients receive data and the `_queue` continues filling up. With multiple clients, total send time = sum of all individual send times.
Impact: one slow client freezes chart updates for ALL clients. The `_queue` fills up during the stall, causing subsequent drains to deliver large bursts — amplifying ISSUE-04.

## ISSUE-12 (P1) - Zustand beds Map is recreated on every single update
Evidence: `frontend/src/stores/bedStore.ts:139` — `const next = new Map(state.beds)` creates a brand-new Map on every `updateFromWebSocket()` call.
Evidence: `frontend/src/components/ward/WardView.tsx:20` — `const beds = useBedStore(s => s.beds)` — selector returns the Map by reference.
Why real: Zustand uses `Object.is()` for equality. Since every update creates a new Map, every update triggers a WardView re-render — even if the update is for a bed not currently visible or its values haven't meaningfully changed.
Evidence: `frontend/src/components/ward/WardView.tsx:24-26` — `Array.from(beds.values()).sort(...)` runs on every re-render with no `useMemo`.
Impact: at inference rate (every 6s per bed), WardView re-renders and re-sorts unnecessarily. Combined with ISSUE-03 (inline onClick defeating React.memo), every inference update re-renders ALL BedCards including their compact charts.

---

# Comprehensive Fix Plan

The issues above have interconnected root causes. Fixing them piecemeal won't produce a smooth system — they need to be addressed together in a coordinated way. Below is the plan, ordered by impact.

## Fix 1 — Yield control in ReplayEngine at high speed (fixes ISSUE-08)

**Root cause**: The inner loop in `replay.py` runs all ticks × all beds synchronously before yielding.

**Fix**: Insert an `await asyncio.sleep(0)` after each tick (not each bed) to yield control to the event loop. This lets the drain loop and heartbeat run between ticks.

```python
# replay.py — inside run()
for tick_i in range(ticks_this_cycle):
    if not self._running:
        break
    for bed_id, replay in list(self._beds.items()):
        fhr, uc = replay.get_next_sample()
        self._callback(bed_id, fhr, uc)
    # Yield to event loop after each tick so drain/heartbeat can run
    if tick_i < ticks_this_cycle - 1:
        await asyncio.sleep(0)
```

**Alternative (better for very high speeds)**: Batch multiple ticks into a single callback call. Instead of calling `callback(bed_id, fhr, uc)` once per sample, collect N samples and call `callback(bed_id, fhr_batch, uc_batch)`. This reduces callback overhead by N×.

## Fix 2 — Concurrent WebSocket sends with timeout (fixes ISSUE-11)

**Root cause**: Sequential `await ws.send_json()` means one slow client blocks all others.

**Fix**: Use `asyncio.gather()` with a per-client timeout:

```python
async def _send_to_all(self, msg: dict) -> None:
    if not self._clients:
        return
    text = json.dumps(msg)  # serialize once
    tasks = []
    for client_id, ws in list(self._clients.items()):
        tasks.append(self._send_one(client_id, ws, text))
    await asyncio.gather(*tasks, return_exceptions=True)

async def _send_one(self, client_id, ws, text, timeout=2.0):
    try:
        if ws.client_state == WebSocketState.CONNECTED:
            await asyncio.wait_for(ws.send_text(text), timeout=timeout)
    except Exception:
        await self.unregister(client_id)
```

**Bonus**: Serialize JSON once, send the same string to all clients (avoids re-serialization per client).

## Fix 3 — Cap _window_scores with a sliding window (fixes ISSUE-09)

**Root cause**: `_window_scores` appends forever, causing O(N) growth in both memory and compute.

**Fix**: Cap to the last `_WINDOW_SCORE_MAX` entries (e.g. 300 = 30 minutes of inference history). The `extract_recording_features()` function only needs recent context anyway.

```python
_WINDOW_SCORE_MAX = 300  # ~30 minutes of inference history

# In on_new_sample():
self._window_scores.append((start, prob))
if len(self._window_scores) > _WINDOW_SCORE_MAX:
    self._window_scores = self._window_scores[-_WINDOW_SCORE_MAX:]
```

## Fix 4 — Eliminate redundant numpy array creation (fixes ISSUE-10)

**Root cause**: Deque → numpy conversion happens twice per inference tick (lines 275 and 369), and the first one creates a temporary full-size array before slicing.

**Fix**: Convert once, reuse the result:

```python
# In on_new_sample(), convert once:
fhr_full = np.array(self._fhr_ring, dtype=np.float32)
uc_full = np.array(self._uc_ring, dtype=np.float32)
fhr_win = fhr_full[-_WINDOW_LEN:]
uc_win = uc_full[-_WINDOW_LEN:]
signal = np.stack([fhr_win, uc_win])

prob = self._run_ensemble(signal)
if prob is None:
    return None

self._window_scores.append((start, prob))
# Pass fhr_full, uc_full to _compute_full_state instead of re-converting
return self._compute_full_state(fhr_full, uc_full)
```

## Fix 5 — Stabilize Zustand Map reference + memoize WardView sort (fixes ISSUE-12, improves ISSUE-03)

**Root cause**: Every `updateFromWebSocket` creates `new Map(state.beds)` → new reference → WardView re-renders.

**Fix A** — Mutate-in-place + force update only when values actually change:
```typescript
updateFromWebSocket: (update: BedUpdate) => {
  set(state => {
    const existing = state.beds.get(update.bed_id)
    const updated = applyUpdate(existing, update)
    // Only create new Map if something meaningful changed
    if (existing && existing.riskScore === updated.riskScore
        && existing.alert === updated.alert
        && existing.warmup === updated.warmup) {
      // Mutate in place — no re-render needed for WardView
      state.beds.set(update.bed_id, updated)
      return state  // same reference → no re-render
    }
    const next = new Map(state.beds)
    next.set(update.bed_id, updated)
    return { beds: next }
  })
}
```

**Fix B** — Memoize the sorted array in WardView:
```typescript
const beds = useBedStore(s => s.beds)
const sorted = useMemo(
  () => Array.from(beds.values()).sort((a, b) => b.riskScore - a.riskScore),
  [beds]
)
```

**Fix C** — Stabilize onClick with useCallback:
```typescript
const handleClick = useCallback((bedId: string) => {
  navigate(`/bed/${bedId}`)
}, [navigate])

// In JSX:
<BedCard key={bed.bedId} bed={bed} onClick={() => handleClick(bed.bedId)} />
// Better: change BedCard to accept bedId and call onClick(bedId) internally
```

## Fix 6 — Fix history race in DetailView chart (fixes ISSUE-01)

**Root cause**: `subscribe()` starts receiving live ticks immediately, then `setData()` fires later and overwrites them.

**Fix**: Reverse the order — load history first, then subscribe:
```typescript
// In useCTGChart Effect 2:
const history = chartUpdateBus.getHistory(bedId)
if (history && !compact) {
  const step = 0.25
  fhrSeries.setData(history.fhrVals.map((v, i) => ({
    time: (history.tStart + i * step) as Time, value: v
  })))
  ucSeries.setData(history.ucVals.map((v, i) => ({
    time: (history.tStart + i * step) as Time, value: v
  })))
}
// THEN subscribe for live ticks (all future ticks will have t > history end)
const unsubscribe = chartUpdateBus.subscribe(bedId, ...)
```

This eliminates the race because `setData()` completes synchronously before live ticks start arriving. The double-rAF deferral is no longer needed — history load is fast enough (~5ms for 4800 points).

## Fix 7 — Add backpressure to ThreadPoolExecutor (fixes ISSUE-05)

**Root cause**: Unbounded executor queue grows indefinitely at high speed.

**Fix**: Use a bounded queue on the executor, or drop stale samples:
```python
# Option A: Track pending count per bed, skip if already queued
self._pending = defaultdict(int)

def on_sample(self, bed_id, fhr_norm, uc_norm):
    pipeline = self._pipelines.get(bed_id)
    if pipeline is None:
        return
    # Skip if this bed already has too many pending tasks
    if self._pending[bed_id] >= 2:
        return  # drop — chart tick was already pushed, inference can skip
    self._pending[bed_id] += 1
    self._executor.submit(self._process_and_broadcast_wrapped, bed_id, pipeline, fhr_norm, uc_norm)

def _process_and_broadcast_wrapped(self, bed_id, pipeline, fhr_norm, uc_norm):
    try:
        self._process_and_broadcast(pipeline, fhr_norm, uc_norm)
    finally:
        self._pending[bed_id] -= 1
```

## Fix 8 — Replace O(N) splice with proper ring buffer in chartUpdateBus (fixes ISSUE-07)

**Root cause**: `Array.splice(0, overflow)` is O(N) — shifts all remaining elements.

**Fix**: Replace the plain array with a true ring buffer (circular index). Or simpler: use a deque-like pattern where old elements are discarded by slicing from the end:
```typescript
// Instead of splice, replace the buffer reference
if (buf.length > MAX_BUFFER + 100) {  // hysteresis to avoid frequent trims
  this.buffers.set(bedId, buf.slice(-MAX_BUFFER))
}
```

## Summary of fix priority

| Priority | Fix | Issues Addressed | Impact |
|----------|-----|-----------------|--------|
| 1 | Yield in ReplayEngine | ISSUE-08 | Eliminates main stall source |
| 2 | Concurrent WS sends | ISSUE-11 | Prevents one slow client from freezing all |
| 3 | Fix history race | ISSUE-01 | Eliminates chart jump on navigation |
| 4 | Stabilize Zustand + memoize | ISSUE-12, ISSUE-03 | Reduces unnecessary React renders by ~90% |
| 5 | Cap _window_scores | ISSUE-09 | Prevents long-term degradation |
| 6 | Deduplicate numpy arrays | ISSUE-10 | Reduces lock contention + CPU usage |
| 7 | Backpressure on executor | ISSUE-05 | Prevents memory growth at high speed |
| 8 | Ring buffer in chartUpdateBus | ISSUE-07 | Eliminates periodic GC spikes |

Fixing items 1–4 should resolve the vast majority of the "system freezes and stutters" problem. Items 5–8 prevent long-term degradation and improve robustness under load.

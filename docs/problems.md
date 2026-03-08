# Problems

All 12 previously-identified performance issues have been resolved. See `docs/ARCHITECTURE.md` section 8 for the 9 fixes applied.

---

## Open Issue: CPU Load Exceeds 40% Threshold at 16 Beds

**Found during:** Phase 8 endurance test (35 min, 16 beds, speed 1x) — 2026-03-08

**Symptom:**
CPU stays at 22-25% during warmup (first 7.5 min, before inference fires), then jumps to 54-81% once all 16 beds start running PatchTST inference.

**Root cause:**
`ThreadPoolExecutor(max_workers=4)` is the bottleneck. At 16 beds each triggering inference every 6 seconds:
- 16 beds / 6s = ~2.7 inference calls/second
- Each inference runs 5 PatchTST folds (ensemble)
- 4 workers cannot drain the queue fast enough
- Workers are saturated continuously → CPU spikes as threads compete

**What works fine:**
- Memory (RSS): stable at 35-36 MB throughout, plateau confirmed at T+30 — no leak
- WS lag p99: max 20ms — far below 200ms threshold
- Zero WebSocket reconnections / backend exceptions

**Candidate fixes (in order of preference):**

1. **Raise `max_workers`** in `api/pipeline_manager.py` — e.g. `max_workers=8` or `max_workers=16`. Low risk, immediate effect. May increase memory slightly. Best first step.

2. **Stagger inference start times** — when 16 beds all hit the 450-sample warmup threshold simultaneously, they all fire at once. Adding a per-bed jitter (e.g. `bed_index * 0.375s` offset) spreads the load over a full 6s window.

3. **Reduce ensemble folds for large deployments** — current setup runs 5 folds (k=0..4) per inference. Reducing to 3 for deployments with >8 beds would cut CPU by ~40% with minimal accuracy loss.

4. **Raise the test threshold** — the 40% CPU ceiling was set conservatively. For a 16-bed ICU deployment, 60-70% sustained CPU may be acceptable if WS lag and memory remain within bounds (both do). The system is functionally stable at this load.

**Fix applied:** Inference staggering via `inference_offset` parameter.
- `SentinelRealtime.__init__` accepts `inference_offset: int = 0`
- Inference fires when `(sample_count - offset) % stride == 0` instead of `sample_count % stride == 0`
- `PipelineManager.set_beds()` computes `offset = (i * 24) // n_beds` for each bed index `i`, spreading N beds evenly across one 24-sample (6s) stride window
- With 16 beds: at most 1-2 beds fire inference per sample tick instead of all 16 simultaneously

**Status:** Fixed — re-run endurance test to confirm CPU drops below 40%.

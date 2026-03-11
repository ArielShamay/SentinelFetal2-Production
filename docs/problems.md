# Phase 7 Review Findings

Date: 2026-03-10
Scope: current implementation of chart streaming and chart history buffering in `api/`, `src/`, and `frontend/`.

Important context:
- `AGENTS.md` and `PLAN.md` no longer use the same phase numbering.
- This review was performed against `PLAN.md` stage 7 (`4 Hz Chart Streaming`) and stage 8 (`Chart History Buffer`), because those are the stages implemented by the chart-streaming code under review.
- Only code-verified findings are listed below.

---

## ISSUE-01 (P0) - `bedStore` suppresses almost all live UI updates after the first snapshot

Evidence:
- `frontend/src/stores/bedStore.ts:58-120` — `applyUpdate(existing, u)` mutates the existing `BedData` object in place.
- `frontend/src/stores/bedStore.ts:149` — `updateFromWebSocket()` can return `state` unchanged (`same reference -> no re-render`).
- The comparison in `updateFromWebSocket()` is performed **after** `applyUpdate()` has already mutated `existing`, so `existing` and `updated` are the same object with the same post-mutation values.

Why real:
- For an existing bed, `existing === updated` after `applyUpdate()` returns.
- Therefore checks like `existing.riskScore === updated.riskScore` and `existing.sampleCount === updated.sampleCount` are always true.
- The store returns the original `state` object, so Zustand does not notify subscribers.

Impact:
- Ward and detail views can stop re-rendering on new `BedUpdate` messages even though the underlying object was mutated.
- This is worse than the earlier render-storm problem: the UI can become stale while chart ticks continue to move, creating the impression that the app is partially frozen.
- Even if a new `Map` were created later, `BedCard` still receives the same mutated `bed` object reference, which interacts badly with `React.memo`.

---

## ISSUE-02 (P0) - Inference stride was changed from the production contract (`24`) to a hard-coded `40`

Evidence:
- `artifacts/production_config.json:6` — `"inference_stride": 24`.
- `src/inference/pipeline.py:46` — `_INFERENCE_STRIDE = 40`.
- `api/services/pipeline_manager.py:154` — manager hard-codes `_INFERENCE_STRIDE = 40` to match the pipeline.
- `src/inference/pipeline.py:392-395` and `src/inference/pipeline.py:427-429` — `_INFERENCE_STRIDE` is passed into `extract_recording_features()`.

Why real:
- The production artifacts and the documented contract were built around an inference stride of 24 samples.
- The current code now runs inference every 40 samples (10 seconds) while still assembling LR features using that new stride.
- This is not a cosmetic change. It changes the temporal meaning of the 12 AI features that feed the trained LR meta-classifier.

Impact:
- Risk scores are no longer computed under the same timing assumptions as the trained production artifacts.
- `window_prob`, `risk_delta`, warmup/inference cadence, and per-bed state freshness all drift from the documented production behavior.
- Any performance conclusions drawn from the current implementation are confounded by a model-contract change, not just a scheduling change.

---

## ISSUE-03 (P1) - Chart tick timestamps can still duplicate or go out of order under per-bed concurrency

Evidence:
- `api/services/pipeline_manager.py:251-252` — timestamp `t` is computed from `pipeline.current_sample_count + 1` and pushed **before** `pipeline.on_new_sample()` acquires the pipeline lock and increments the counter.
- `api/services/pipeline_manager.py:215-218` — multiple pending tasks per bed are still allowed (`_pending[bed_id] >= 50`).

Why real:
- Two worker threads for the same bed can read the same `current_sample_count` before either thread enters `on_new_sample()`.
- Both threads then emit the same chart timestamp `t`.
- The frontend update path uses `series.update()`; out-of-order or duplicate times are ignored or can throw internally, and the current code explicitly swallows those failures in `useCTGChart.ts`.

Impact:
- Missing or dropped chart points remain possible under load.
- This directly undermines the core promise of stage 7: smooth 4 Hz chart motion independent of inference.

---

## ISSUE-04 (P1) - WebSocket batch processing still runs synchronously on the browser main thread

Evidence:
- `frontend/src/hooks/useBedStream.ts:36-40` — one message event loops synchronously over all `updates` and then all `chart_ticks`.
- `frontend/src/hooks/useCTGChart.ts:122-134` — each published batch is processed synchronously and calls `series.update()` once per sample.

Why real:
- All of this work runs inside one JavaScript message event without yielding.
- Reconnect bursts, higher replay speeds, or multi-bed traffic can produce long tasks on the UI thread.

Impact:
- Frame drops and visible stutter remain possible even after the history-race fix.
- The chart stream is decoupled from React state, but it is still not decoupled from the browser main thread.

---

## ISSUE-05 (P1) - Backend still delivers chart ticks in bursts instead of an even 4 Hz flow

Evidence:
- `api/services/broadcaster.py:32` — fixed `_DRAIN_INTERVAL = 0.05`.
- `api/services/broadcaster.py:125-140` — each drain cycle empties the whole queue and sends one combined `batch_update` containing all accumulated `chart_ticks`.

Why real:
- Producer timing and drain timing are independent.
- The receiver gets bursts of queued ticks every drain cycle, not a steady sample-by-sample stream.

Impact:
- Even with correct backend sample production, the chart can still look jittery because data arrives in chunks.
- This is a remaining architectural limitation of the stage 7 design.

---

## ISSUE-06 (P1) - Backend and frontend wire schemas are out of sync for `chart_ticks`

Evidence:
- `api/services/broadcaster.py:136-140` sends `chart_ticks` inside every `batch_update`.
- `frontend/src/types/index.ts:55-59` expects `BatchUpdateMessage.chart_ticks`.
- `api/models/schemas.py:56-59` defines `BatchUpdateMessage` with `updates` only and omits `chart_ticks` entirely.

Why real:
- The backend schema file no longer mirrors the actual wire format.
- The file comment at the top of `frontend/src/types/index.ts` says the frontend types mirror `api/models/schemas.py`, but that is currently false.

Impact:
- OpenAPI/docs/tests based on the backend schemas are now wrong.
- Future code that starts validating WebSocket payloads against `BatchUpdateMessage` will reject the real payload or silently ignore `chart_ticks`.

---

## ISSUE-07 (P2) - Stage 8 history contract regressed for compact ward charts

Evidence:
- `PLAN.md:3318-3330` states that every bed should always retain chart history and opening any bed should show immediate history.
- `frontend/src/hooks/useCTGChart.ts:102` explicitly states: `Compact mini-charts skip history entirely`.
- `frontend/src/components/ward/BedCard.tsx:81` renders a compact `CTGChart` for every bed card.

Why real:
- The buffer still exists in `chartUpdateBus`, but compact charts intentionally do not consume it.
- On ward mount or return to ward view, mini charts start empty and refill only from new live ticks.

Impact:
- The current implementation no longer fully matches the stage 8 contract.
- This is not the main stall source, but it is a functional regression introduced in the chart path.

---

## ISSUE-08 (P2) - Backpressure is still incomplete because the broadcaster queue is unbounded

Evidence:
- `api/services/pipeline_manager.py:215-218` limits executor submission per bed, which is an improvement.
- `api/services/broadcaster.py:39` still constructs `queue.Queue()` with no `maxsize`.
- `api/services/broadcaster.py:45-67` still accepts unlimited `state` and `tick` enqueues.

Why real:
- Executor backpressure reduces one source of runaway growth, but the WebSocket broadcast queue itself can still accumulate without bound if production outpaces draining.
- Slow-client handling was improved, but queue growth is still not bounded by policy.

Impact:
- Under sustained load, latency can still rise through queue accumulation.
- This keeps the stage 7 stream vulnerable to burst amplification even after the send-path fixes.

---

## Summary

The current implementation is not in the state described by the previous `problems.md` revision. The most serious remaining issues are:

1. `bedStore` now suppresses live UI updates because of in-place mutation plus `return state`.
2. The inference contract was changed from stride `24` to `40`, which invalidates the timing assumptions of the production feature pipeline.
3. Chart tick ordering is still not serialized per bed before timestamps are emitted.

These are code-level findings from the current implementation, not speculative risks.

---

## P2 - validate_artifacts.py ignores --weights-dir CLI flag

**Evidence:**
- scripts/validate_artifacts.py parses --weights-dir but never uses it.
- Weight validation always uses paths from production_config.json (validate_weights(cfg["weights"]))

**Impact:**
Running python scripts/validate_artifacts.py --weights-dir ... does not change
the validation target, which is misleading and makes the CLI contract inaccurate.

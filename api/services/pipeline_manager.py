"""
api/services/pipeline_manager.py — PipelineManager: orchestrates all per-bed pipelines.

Design (PLAN.md §4, §9, §11.1 BUG-2/BUG-8):
  - PipelineManager.__init__(broadcaster, ...) — broadcaster FIRST (BUG-2)
  - on_sample() submits to ThreadPoolExecutor — never blocks event loop
  - _process_and_broadcast() runs in thread: on_new_sample → alert_history.record → broadcaster.push
  - push() is synchronous queue.put_nowait — NO run_coroutine_threadsafe, NO self._loop (BUG-8)
  - set_beds() atomically replaces bed config across engine + pipelines
"""
from __future__ import annotations

import logging
import random
import threading
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.inference.pipeline import BedState, SentinelRealtime
    from api.services.broadcaster import AsyncBroadcaster

logger = logging.getLogger(__name__)
audit_logger = logging.getLogger("sentinel.audit")

MAX_BEDS = 16


class PipelineManager:
    """
    Manages up to MAX_BEDS SentinelRealtime instances.

    Thread-safety model:
      - on_sample() is called from the async event loop (ReplayEngine.run)
      - inference (_process_and_broadcast) runs in ThreadPoolExecutor
      - push() on broadcaster is sync/thread-safe (queue.put_nowait)
      - _pipelines dict and _last_states dict are protected by _lock

    BUG-2: broadcaster is first param — must be alive before first on_sample().
    BUG-8: no self._loop stored — push() is sync, no asyncio bridge needed.
    """

    def __init__(
        self,
        broadcaster: "AsyncBroadcaster",
        models: list,
        scaler,
        lr_model,
        config: dict,
        recordings_dir: Path = Path("data/recordings"),
    ) -> None:
        # broadcaster FIRST — required to be alive before pipelines emit states (BUG-2)
        self._broadcaster = broadcaster
        self._models = models
        self._scaler = scaler
        self._lr_model = lr_model
        self._config = config
        self._recordings_dir = recordings_dir

        self._pipelines: dict[str, "SentinelRealtime"] = {}
        self._last_states: dict[str, "BedState"] = {}
        self._lock = threading.Lock()

        # Limit CPU saturation: max 4 concurrent PatchTST inference threads (§9)
        self._executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="sentinel-inf")
        # Backpressure: track pending tasks per bed to prevent unbounded queue growth
        self._pending: dict[str, int] = defaultdict(int)

        self._god_mode_enabled: bool = False
        self._baseline_recordings: dict[str, str] = {}   # bed_id → original recording_id (BUG-11)

        # God Mode segment store — loaded if catalog exists
        self._segment_store = None
        try:
            from src.god_mode.segment_store import SegmentStore
            self._segment_store = SegmentStore()
        except Exception as exc:
            logger.info("SegmentStore not available (catalog may not exist yet): %s", exc)

        # Import deferred to avoid circular import at module level
        from api.services.alert_history import AlertHistoryStore
        from api.services.note_store import NoteStore

        self._alert_history = AlertHistoryStore()
        self._note_store = NoteStore()

    # ── Public: note & alert access ────────────────────────────────────────

    @property
    def alert_history(self):
        return self._alert_history

    @property
    def note_store(self):
        return self._note_store

    # ── God Mode (system-wide toggle, Phase 4 uses this) ──────────────────

    @property
    def god_mode_enabled(self) -> bool:
        return self._god_mode_enabled

    def enable_god_mode(self) -> None:
        """Enable God Mode for all existing and future pipelines."""
        self._god_mode_enabled = True
        with self._lock:
            for pipeline in self._pipelines.values():
                pipeline._god_mode = True
                # Pipelines created before god_mode was toggled have _injector=None.
                # Mirror the init logic: attempt to acquire the injector now so that
                # activation is fully contractual (BUG-4: flag + injector both set).
                if pipeline._injector is None:
                    try:
                        from src.god_mode.injector import GodModeInjector  # type: ignore[import]
                        pipeline._injector = GodModeInjector.get()
                    except ImportError:
                        pass  # Phase 4 not yet available — silently disabled
        audit_logger.info("GOD_MODE_ENABLED | system-wide")

    def get_baseline_recording(self, bed_id: str) -> str | None:
        """Return the original recording_id assigned to a bed (BUG-11).

        Used by God Mode to always restore to the true baseline, even after
        multiple overlapping signal swaps.
        """
        return self._baseline_recordings.get(bed_id)

    # ── Bed management ─────────────────────────────────────────────────────

    def set_beds(self, bed_configs: list[dict], engine) -> None:
        """
        Atomically replace all active beds.

        bed_configs: [{"bed_id": "bed_01", "recording_id": "1001"}, ...]
        If recording_id is None, a random .npy is selected.
        engine: ReplayEngine — its set_beds() is called to sync recording routing.
        """
        if len(bed_configs) > MAX_BEDS:
            raise ValueError(f"Cannot configure more than {MAX_BEDS} beds")

        resolved: list[dict] = []
        used_recordings: set[str] = set()
        for cfg in bed_configs:
            rid = cfg.get("recording_id") or self._pick_random_recording(exclude=used_recordings)
            used_recordings.add(rid)
            resolved.append({"bed_id": cfg["bed_id"], "recording_id": rid})

        from src.inference.pipeline import SentinelRealtime

        new_pipelines: dict[str, SentinelRealtime] = {}
        for cfg in resolved:
            bid = cfg["bed_id"]
            rid = cfg["recording_id"]
            new_pipelines[bid] = SentinelRealtime(
                bed_id=bid,
                recording_id=rid,
                models=self._models,
                scaler=self._scaler,
                lr_model=self._lr_model,
                config=self._config,
                god_mode=self._god_mode_enabled,
            )

        engine.set_beds(resolved)

        with self._lock:
            self._pipelines = new_pipelines
            # Clear last states so initial_state doesn't send stale data
            self._last_states = {}
            # BUG-11: remember original recording per bed for God Mode restore
            self._baseline_recordings = {c["bed_id"]: c["recording_id"] for c in resolved}

        logger.info("Beds configured: %s", [c["bed_id"] for c in resolved])

    def get_pipeline(self, bed_id: str) -> "SentinelRealtime | None":
        return self._pipelines.get(bed_id)

    def get_bed_states(self) -> list["BedState"]:
        """Return latest cached BedState for all active beds (snapshot)."""
        with self._lock:
            return list(self._last_states.values())

    def get_last_state(self, bed_id: str) -> "BedState | None":
        with self._lock:
            return self._last_states.get(bed_id)

    def active_bed_ids(self) -> list[str]:
        with self._lock:
            return list(self._pipelines.keys())

    # ── Hot path: called at 4 Hz from event loop ──────────────────────────

    def on_sample(self, bed_id: str, fhr_norm: float, uc_norm: float) -> None:
        """
        Called by ReplayEngine at 4 Hz from the async event loop thread.
        Non-blocking: submits inference work to ThreadPoolExecutor and returns immediately.
        PatchTST inference (~50ms) runs off the event loop (BUG-8 prevention).
        Backpressure: at extreme speed (20× with 16 beds), cap per-bed pending
        tasks to prevent unbounded memory growth while still allowing enough
        throughput for warmup and inference to complete.
        """
        pipeline = self._pipelines.get(bed_id)
        if pipeline is None:
            return
        if self._pending[bed_id] >= 50:
            return  # backpressure — extreme load protection only
        self._pending[bed_id] += 1
        self._executor.submit(self._process_and_broadcast_wrapped, bed_id, pipeline, fhr_norm, uc_norm)

    def _process_and_broadcast_wrapped(
        self,
        bed_id: str,
        pipeline: "SentinelRealtime",
        fhr_norm: float,
        uc_norm: float,
    ) -> None:
        """Wrapper that decrements pending counter after processing."""
        try:
            self._process_and_broadcast(pipeline, fhr_norm, uc_norm)
        finally:
            self._pending[bed_id] -= 1

    def _process_and_broadcast(
        self,
        pipeline: "SentinelRealtime",
        fhr_norm: float,
        uc_norm: float,
    ) -> None:
        """
        Runs in ThreadPoolExecutor — CPU-heavy inference off the event loop.

        push() is sync and thread-safe (queue.put_nowait) — no asyncio bridge needed.
        """
        try:
            # Chart tick is pushed BEFORE on_new_sample() so that PatchTST inference
            # (which runs every _INFERENCE_STRIDE samples and takes ~200ms) cannot delay
            # the 4 Hz chart stream. t is pre-computed as (count+1)/4.0 to match the
            # post-increment sample index that on_new_sample() will assign.
            fhr_bpm = round(fhr_norm * 160.0 + 50.0, 1)
            uc_mmhg = round(uc_norm * 100.0, 1)
            t = (pipeline.current_sample_count + 1) / 4.0
            self._broadcaster.push_chart_tick(pipeline.bed_id, fhr_bpm, uc_mmhg, t)

            state = pipeline.on_new_sample(fhr_norm, uc_norm)

            if state is None:
                return

            # Cache latest state for initial_state responses + REST /beds endpoint
            with self._lock:
                self._last_states[state.bed_id] = state

            # Alert transition logging (§11.3)
            self._alert_history.record(state)

            # Broadcast to all WebSocket clients (sync, thread-safe)
            self._broadcaster.push(state)

        except Exception:
            logger.exception("Error in _process_and_broadcast for pipeline %s", pipeline)

    # ── Helpers ───────────────────────────────────────────────────────────

    def _pick_random_recording(self, exclude: set[str] | None = None) -> str:
        """Pick a random recording_id from data/recordings/, avoiding already-used ones."""
        npy_files = list(self._recordings_dir.glob("*.npy"))
        if not npy_files:
            raise RuntimeError(f"No .npy files found in {self._recordings_dir}")
        exclude = exclude or set()
        available = [f for f in npy_files if f.stem not in exclude]
        if not available:
            available = npy_files  # fallback: more beds than unique recordings
        return random.choice(available).stem   # filename without extension, e.g. "1001"

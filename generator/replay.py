"""
generator/replay.py � CTG recording replay at 4 Hz
====================================================

Reads .npy files from data/recordings/ and streams samples at 4 Hz
to simulate a live CTG device.

.npy files are PRE-NORMALIZED (produced by src/data/preprocessing.py):
  Channel 0 — FHR: normalized [0, 1] = (bpm - 50) / 160
  Channel 1 — UC:  normalized [0, 1] = mmHg / 100

Usage:
    replay = RecordingReplay("1001", "data/recordings")
    fhr_norm, uc_norm = replay.get_next_sample()   # values in [0, 1]

    engine = ReplayEngine({"bed_01": "1001"}, "data/recordings", callback, speed=1.0)
    asyncio.run(engine.run())
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# RecordingReplay — single recording, infinite loop
# ---------------------------------------------------------------------------


class RecordingReplay:
    """
    Streams a single .npy recording at 4 Hz.
    Loops infinitely when the recording ends.
    """

    def __init__(self, recording_id: str, recordings_dir: Path | str) -> None:
        self._recording_id = str(recording_id)
        self._dir = Path(recordings_dir)
        self._fhr: np.ndarray
        self._uc: np.ndarray
        self._pos: int = 0
        self._load()

    # ── internal ─────────────────────────────────────────────────────────

    def _load(self) -> None:
        path = self._dir / f"{self._recording_id}.npy"
        data = np.load(path)  # shape: (2, T) — already normalized
        fhr_norm = data[0].astype(np.float32)
        uc_norm  = data[1].astype(np.float32)
        # Handle residual NaN: 0.5 = 130 bpm normalized; 0.0 = 0 mmHg
        fhr_norm = np.nan_to_num(fhr_norm, nan=0.5)
        uc_norm  = np.nan_to_num(uc_norm,  nan=0.0)
        self._fhr = fhr_norm
        self._uc  = uc_norm
        self._pos = 0

    # ── public API ────────────────────────────────────────────────────────

    def get_next_sample(self) -> tuple[float, float]:
        """
        Returns (fhr_norm, uc_norm) — normalized [0, 1].
        ⚠ NOT bpm/mmHg — the .npy files are pre-normalized at preprocessing time.
        Caller (SentinelRealtime.on_new_sample) expects normalized input directly.
        For display: bpm = fhr_norm * 160 + 50, mmHg = uc_norm * 100.
        Loops infinitely: wraps around to position 0 when the recording ends.
        """
        if self._pos >= len(self._fhr):
            self._pos = 0
        fhr = float(self._fhr[self._pos])
        uc  = float(self._uc[self._pos])
        self._pos += 1
        return fhr, uc

    def reset(self) -> None:
        """Reset playback position to the start of the recording."""
        self._pos = 0

    def seek(self, sample_index: int) -> None:
        """Set playback position to a specific sample index."""
        self._pos = max(0, min(sample_index, len(self._fhr) - 1))

    @property
    def position_seconds(self) -> float:
        """Current playback position in seconds (at 4 Hz)."""
        return self._pos / 4.0

    @property
    def recording_id(self) -> str:
        return self._recording_id


# ---------------------------------------------------------------------------
# ReplayEngine — manages up to 16 beds
# ---------------------------------------------------------------------------


class ReplayEngine:
    """
    Manages up to 16 beds, each replaying a .npy recording.
    Drives samples at 4 Hz (0.25 s per outer cycle) via an async loop.

    At speed > 1, delivers round(speed) samples per bed per 0.25 s cycle,
    compressing recording time proportionally (e.g. 10× → 10 samples/0.25s).
    """

    MAX_BEDS = 16

    def __init__(
        self,
        beds: dict[str, str],
        recordings_dir: Path | str,
        callback: Callable[[str, float, float], None],
        speed: float = 1.0,
    ) -> None:
        """
        Args:
            beds:           mapping bed_id → recording_id.
            recordings_dir: path to directory containing .npy files.
            callback:       called with (bed_id, fhr_norm, uc_norm) for every sample.
                            Must be NON-BLOCKING (e.g. submit to ThreadPoolExecutor).
            speed:          playback multiplier [1.0, 20.0]. Default 1× = realtime (4 Hz).
        """
        self._dir = Path(recordings_dir)
        self._callback = callback
        self._speed: float = 1.0   # default; set_speed() validates and overwrites
        self._beds: dict[str, RecordingReplay] = {}
        self._running: bool = False
        self._paused: bool = False
        self._tick_count: int = 0

        self.set_speed(speed)  # P1 fix: validated path — raises AssertionError if out of [1.0, 20.0]

        for bed_id, recording_id in beds.items():
            self.add_bed(bed_id, recording_id)

    # ── bed management ────────────────────────────────────────────────────

    def add_bed(self, bed_id: str, recording_id: str) -> None:
        """Register a bed. Raises ValueError if MAX_BEDS exceeded."""
        if len(self._beds) >= self.MAX_BEDS:
            raise ValueError(
                f"Cannot add bed '{bed_id}': MAX_BEDS ({self.MAX_BEDS}) reached"
            )
        self._beds[bed_id] = RecordingReplay(recording_id, self._dir)
        logger.info("ReplayEngine: added bed '%s' → recording '%s'", bed_id, recording_id)

    def remove_bed(self, bed_id: str) -> None:
        """Unregister a bed. Silent no-op if bed is not registered."""
        if bed_id in self._beds:
            del self._beds[bed_id]
            logger.info("ReplayEngine: removed bed '%s'", bed_id)

    def set_beds(self, bed_configs: list[dict]) -> None:
        """
        Atomic replacement of all beds.
        bed_configs = [{"bed_id": "bed_01", "recording_id": "1023"}, ...]
        Raises ValueError if len(bed_configs) > MAX_BEDS.
        """
        if len(bed_configs) > self.MAX_BEDS:  # P2 fix: enforce MAX_BEDS consistently
            raise ValueError(
                f"set_beds: received {len(bed_configs)} beds, MAX_BEDS is {self.MAX_BEDS}"
            )
        new_beds: dict[str, RecordingReplay] = {}
        for cfg in bed_configs:
            new_beds[cfg["bed_id"]] = RecordingReplay(cfg["recording_id"], self._dir)
        self._beds = new_beds   # atomic dict replace in CPython (GIL-protected)

    # ── speed control ─────────────────────────────────────────────────────

    def set_speed(self, speed: float) -> None:
        """
        Set playback speed. Thread-safe (float assignment is atomic in CPython).
        Supported range: [1.0, 20.0]. Slow-motion (<1×) is not supported.
        Effective on the next tick iteration.
        """
        assert 1.0 <= speed <= 20.0, f"Speed must be in [1.0, 20.0], got {speed}"
        self._speed = speed
        logger.debug("ReplayEngine: speed set to %.1f×", speed)

    # ── lifecycle ─────────────────────────────────────────────────────────

    def pause(self) -> None:
        """Pause sample delivery. Recording positions are preserved."""
        self._paused = True
        logger.debug("ReplayEngine: paused")

    def resume(self) -> None:
        """Resume sample delivery after a pause."""
        self._paused = False
        logger.debug("ReplayEngine: resumed")

    def stop(self) -> None:
        """Signal the run() loop to exit on its next iteration.

        Also clears _paused so that a subsequent run() call starts cleanly
        and does not immediately block in the paused-sleep branch.
        """
        self._running = False
        self._paused = False
        logger.debug("ReplayEngine: stop signalled")

    @property
    def tick_count(self) -> int:
        """Total number of 0.25 s cycles completed since run() started."""
        return self._tick_count

    # ── God Mode: recording swap ───────────────────────────────────────────

    def swap_recording(
        self, bed_id: str, recording_id: str, start_sample: int = 0
    ) -> str | None:
        """Swap the recording source for a specific bed mid-stream.

        Returns the previous recording_id (for restore on event end),
        or None if bed_id not found.

        Does NOT reset the pipeline — new data flows naturally into the
        existing ring buffer. The CTG graph shows the new recording immediately.
        """
        if bed_id not in self._beds:
            return None
        old_recording_id = self._beds[bed_id].recording_id
        new_replay = RecordingReplay(recording_id, self._dir)
        new_replay.seek(start_sample)
        self._beds[bed_id] = new_replay
        logger.info(
            "ReplayEngine: bed '%s' swapped recording %s → %s (start=%d)",
            bed_id, old_recording_id, recording_id, start_sample,
        )
        return old_recording_id

    # ── async loop ────────────────────────────────────────────────────────

    async def run(self) -> None:
        """
        Async loop: fires at 4 Hz (0.25 s per outer cycle).

        Speed control (§11.5):
            ticks_this_cycle = max(1, round(self._speed))
            → at 1×: 1 sample/bed/cycle  (4 Hz effective)
            → at 2×: 2 samples/bed/cycle (8 Hz effective)
            → at 10×: 10 samples/bed/cycle (40 Hz effective)

        ⚠ list(self._beds.items()) snapshot prevents RuntimeError when
          add_bed / remove_bed / set_beds are called concurrently (BUG-4).
        """
        TICK_INTERVAL = 0.25  # seconds — 4 Hz base rate

        self._running = True
        self._paused = False  # defensive: never inherit stale pause from a previous run()
        self._tick_count = 0

        while self._running:
            if self._paused:
                await asyncio.sleep(0.1)
                continue

            t_start = asyncio.get_event_loop().time()
            ticks_this_cycle = max(1, round(self._speed))

            for _ in range(ticks_this_cycle):
                if not self._running:
                    break
                # Snapshot: safe against concurrent add_bed / remove_bed / set_beds
                for bed_id, replay in list(self._beds.items()):
                    fhr, uc = replay.get_next_sample()
                    # callback is NON-BLOCKING by contract:
                    # PipelineManager.on_sample submits to ThreadPoolExecutor
                    # and returns immediately — never block the event loop here.
                    self._callback(bed_id, fhr, uc)

            self._tick_count += 1
            elapsed = asyncio.get_event_loop().time() - t_start
            sleep_time = max(0.0, TICK_INTERVAL - elapsed)
            await asyncio.sleep(sleep_time)

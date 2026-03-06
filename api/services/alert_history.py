"""
api/services/alert_history.py — Server-side alert history & audit log (§11.3).

AlertHistoryStore records alert state *transitions* (false → true, true → false)
for each bed. Keeps last MAX_PER_BED events in memory and appends each to an
append-only JSONL file so history survives server restarts.
"""
from __future__ import annotations

import dataclasses
import json
import logging
import threading
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.inference.pipeline import BedState

logger = logging.getLogger(__name__)
audit_logger = logging.getLogger("sentinel.audit")


@dataclass
class AlertEvent:
    bed_id: str
    timestamp: float
    risk_score: float
    alert_on: bool          # True = alert started, False = alert cleared
    elapsed_s: float        # recording position at event time


class AlertHistoryStore:
    """
    In-memory rolling store: last MAX_PER_BED alert events per bed.
    Persisted to alert_log_path (append-only JSONL) on each write.
    On startup, loads existing log to restore history after restart.
    """

    MAX_PER_BED = 200

    def __init__(self, log_path: Path = Path("data/alert_log.jsonl")) -> None:
        self._log_path = log_path
        self._store: dict[str, deque[AlertEvent]] = {}
        self._last_alert_state: dict[str, bool] = {}
        self._lock = threading.Lock()
        self._load_from_file()

    # ── Public interface ──────────────────────────────────────────────────

    def record(self, state: "BedState") -> None:
        """
        Called from PipelineManager on every BedState emission.
        Records only on alert state *transitions* — not every tick.
        """
        bed_id = state.bed_id
        with self._lock:
            prev = self._last_alert_state.get(bed_id, False)
            if state.alert == prev:
                return   # no transition — skip

            self._last_alert_state[bed_id] = state.alert
            event = AlertEvent(
                bed_id=bed_id,
                timestamp=state.timestamp,
                risk_score=state.risk_score,
                alert_on=state.alert,
                elapsed_s=state.elapsed_seconds,
            )
            self._store.setdefault(bed_id, deque(maxlen=self.MAX_PER_BED)).append(event)

        self._append_to_file(event)

        direction = "ON" if state.alert else "OFF"
        audit_logger.info(
            "ALERT_%s | bed=%s | risk=%.4f | elapsed=%.1fs | recording=%s",
            direction, bed_id, state.risk_score, state.elapsed_seconds,
            getattr(state, "recording_id", "?"),
        )

    def get_history(self, bed_id: str, last_n: int = 50) -> list[AlertEvent]:
        """Return last `last_n` alert events for a bed, oldest-first."""
        with self._lock:
            return list(self._store.get(bed_id, []))[-last_n:]

    def get_all_histories(self) -> dict[str, list[AlertEvent]]:
        """Return all histories (for debug / export)."""
        with self._lock:
            return {bed_id: list(events) for bed_id, events in self._store.items()}

    # ── Persistence ───────────────────────────────────────────────────────

    def _append_to_file(self, event: AlertEvent) -> None:
        """Non-critical write — failures are logged but do not raise."""
        try:
            self._log_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(dataclasses.asdict(event)) + "\n")
        except OSError as exc:
            logger.warning("Alert log write failed: %s", exc)

    def _load_from_file(self) -> None:
        """Load existing alert log on startup to restore in-memory history."""
        if not self._log_path.exists():
            return
        loaded = 0
        try:
            with open(self._log_path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        d = json.loads(line)
                        event = AlertEvent(**d)
                        self._store.setdefault(
                            event.bed_id, deque(maxlen=self.MAX_PER_BED)
                        ).append(event)
                        self._last_alert_state[event.bed_id] = event.alert_on
                        loaded += 1
                    except Exception:
                        pass    # skip malformed lines
        except OSError as exc:
            logger.warning("Could not read alert log: %s", exc)
        if loaded:
            logger.info("Restored %d alert events from %s", loaded, self._log_path)

"""
src/god_mode/injector.py — GodModeInjector singleton
====================================================

Thread-safe singleton that holds active injection events per bed.
Called from SentinelRealtime._compute_full_state() — must be O(1)
when no events are active.

PLAN.md references: §10.4, §10.6
"""

from __future__ import annotations

import logging
import threading

from src.god_mode.overrides import build_feature_override
from src.god_mode.types import EventAnnotation, EventType, InjectionEvent

logger = logging.getLogger(__name__)


def _samples_to_hms(samples: int) -> str:
    """Convert sample count to HH:MM:SS (at 4 Hz)."""
    total_sec = samples / 4.0
    h = int(total_sec // 3600)
    m = int((total_sec % 3600) // 60)
    s = int(total_sec % 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def _sec_to_hms(sec: float) -> str:
    """Convert seconds to HH:MM:SS."""
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = int(sec % 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def _describe_override(clin: list[float], event_type: EventType) -> dict:
    """Build a dict describing what clinical features were overridden."""
    from src.features.clinical_extractor import CLINICAL_FEATURE_NAMES

    details = {}
    if event_type == EventType.LATE_DECELERATIONS:
        details["n_late_decelerations"] = int(clin[5])
        details["max_deceleration_depth_bpm"] = clin[8]
    elif event_type == EventType.VARIABLE_DECELERATIONS:
        details["n_variable_decelerations"] = int(clin[6])
        details["max_deceleration_depth_bpm"] = clin[8]
    elif event_type == EventType.PROLONGED_DECELERATION:
        details["n_prolonged_decelerations"] = int(clin[7])
        details["max_deceleration_depth_bpm"] = clin[8]
    elif event_type == EventType.SINUSOIDAL_PATTERN:
        details["sinusoidal_detected"] = True
    elif event_type == EventType.TACHYSYSTOLE:
        details["tachysystole_detected"] = True
    elif event_type == EventType.BRADYCARDIA:
        details["baseline_bpm"] = clin[0]
        details["is_bradycardia"] = True
    elif event_type == EventType.TACHYCARDIA:
        details["baseline_bpm"] = clin[0]
        details["is_tachycardia"] = True
    elif event_type == EventType.LOW_VARIABILITY:
        details["variability_amplitude_bpm"] = clin[3]
        details["variability_category"] = "absent"
    elif event_type == EventType.COMBINED_SEVERE:
        details["n_late_decelerations"] = int(clin[5])
        details["n_prolonged_decelerations"] = int(clin[7])
        details["variability_category"] = "absent"
        details["tachysystole_detected"] = True
    return details


class GodModeInjector:
    """Thread-safe singleton. Holds active injection events per bed.

    Performance contract:
      - has_active_events(): O(1) when no events — no lock needed
      - compute_override():  O(k) where k = active events (≤5 typical)
    """

    _instance: GodModeInjector | None = None

    def __init__(self) -> None:
        self._events: dict[str, list[InjectionEvent]] = {}   # bed_id → events
        self._lock = threading.Lock()

    @classmethod
    def get(cls) -> GodModeInjector:
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
        """Compute feature overrides for all active events on this bed.

        Returns:
          - modified clin_list (clinical features overridden)
          - modified window_scores (recent windows boosted)
          - list of EventAnnotation objects for UI
        """
        with self._lock:
            events = [
                e for e in self._events.get(bed_id, [])
                if e.start_sample <= current_sample
                and (e.end_sample is None or current_sample <= e.end_sample)
            ]

        clin_out = list(clin_list)
        ws_out = list(window_scores)
        annotations: list[EventAnnotation] = []

        for event in events:
            # Override clinical features
            clin_out = build_feature_override(clin_out, event)

            # Boost recent window_scores so AI features also reflect the problem.
            # BUG-9 fix: use s + 1800 >= event.start_sample (window END, not START).
            min_prob = 0.5 + event.severity * 0.4   # severity 0.5→0.7, 1.0→0.9
            ws_out = [
                (s, max(p, min_prob)) if s + 1800 >= event.start_sample else (s, p)
                for s, p in ws_out
            ]

            # Build annotation for UI
            duration_s = (
                None if event.end_sample is None
                else (event.end_sample - event.start_sample) / 4.0
            )
            still_going = event.end_sample is None or current_sample <= event.end_sample
            start_hms = _samples_to_hms(event.start_sample)
            dur_str = "ongoing" if still_going else f"duration: {_sec_to_hms(duration_s)}"

            annotations.append(EventAnnotation(
                event_id=event.event_id,
                event_type=event.event_type.value,
                start_sample=event.start_sample,
                end_sample=event.end_sample,
                still_ongoing=still_going,
                description=event.description,
                timeline_summary=f"Started {start_hms} | {dur_str}",
                detected_details=_describe_override(clin_out, event.event_type),
            ))

        return clin_out, ws_out, annotations

    # ── Management API ────────────────────────────────────────────────────

    def add_event(self, event: InjectionEvent) -> None:
        with self._lock:
            self._events.setdefault(event.bed_id, []).append(event)
        logger.info(
            "GOD_MODE_INJECT | bed=%s type=%s severity=%.2f event_id=%s signal_swapped=%s",
            event.bed_id, event.event_type.value, event.severity,
            event.event_id, event.signal_swapped,
        )

    def end_event(self, bed_id: str, event_id: str, current_sample: int) -> bool:
        """Mark an ongoing event as ended at current_sample. Returns True if found."""
        with self._lock:
            for e in self._events.get(bed_id, []):
                if e.event_id == event_id and e.end_sample is None:
                    e.end_sample = current_sample
                    logger.info(
                        "GOD_MODE_END | bed=%s event_id=%s end_sample=%d",
                        bed_id, event_id, current_sample,
                    )
                    return True
        return False

    def get_event(self, bed_id: str, event_id: str) -> InjectionEvent | None:
        """Get a specific event by ID."""
        with self._lock:
            for e in self._events.get(bed_id, []):
                if e.event_id == event_id:
                    return e
        return None

    def clear_bed(self, bed_id: str) -> list[InjectionEvent]:
        """Remove all events for a bed. Returns the removed events (for signal restore)."""
        with self._lock:
            removed = self._events.pop(bed_id, [])
        if removed:
            logger.info("GOD_MODE_CLEAR | bed=%s removed=%d events", bed_id, len(removed))
        return removed

    def get_events(self, bed_id: str) -> list[InjectionEvent]:
        with self._lock:
            return list(self._events.get(bed_id, []))

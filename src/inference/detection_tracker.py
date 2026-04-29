"""State-machine tracker for model and rule-based detection events."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from src.inference.explainability import FeatureContribution


@dataclass
class DetectionEvent:
    """Time-bounded detection emitted as a delta to the frontend."""

    event_id: str
    bed_id: str
    source: str
    event_type: str
    start_sample: int
    end_sample: int | None
    still_ongoing: bool
    peak_risk_score: float
    peak_sample: int
    top_contributions: list[FeatureContribution] = field(default_factory=list)
    description: str = ""
    timeline_summary: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


def _format_time(sample: int) -> str:
    seconds = int(sample / 4.0)
    hh = seconds // 3600
    mm = (seconds % 3600) // 60
    ss = seconds % 60
    if hh:
        return f"{hh:02d}:{mm:02d}:{ss:02d}"
    return f"{mm:02d}:{ss:02d}"


def _timeline_summary(start_sample: int, end_sample: int | None) -> str:
    if end_sample is None:
        return f"Started {_format_time(start_sample)} | Ongoing"
    duration_s = max(0, int((end_sample - start_sample) / 4.0))
    mm = duration_s // 60
    ss = duration_s % 60
    return f"Started {_format_time(start_sample)} | Duration: {mm:02d}:{ss:02d}"


class DetectionTracker:
    """Tracks rising/falling edges for explainability events for one bed."""

    def __init__(self, bed_id: str) -> None:
        self._bed_id = bed_id
        self._active: dict[str, DetectionEvent] = {}
        self._seen_deceleration_keys: set[tuple[str, int]] = set()
        self._pending: list[DetectionEvent] = []

    def reset(self) -> None:
        self._active.clear()
        self._seen_deceleration_keys.clear()
        self._pending.clear()

    def update(
        self,
        state: Any,
        x_raw: Any,
        top_contributions: list[FeatureContribution],
        clinical_intervals: list[dict[str, Any]],
    ) -> None:
        """Update tracker from the latest BedState and clinical intervals."""

        del x_raw  # reserved for future rule-specific descriptions

        checks = [
            (
                "lr_high_risk",
                "model",
                bool(state.risk_score > state.alert_threshold),
                f"סיכון גבוה (LR={state.risk_score:.2f})",
                {"risk_score": float(state.risk_score), "threshold": float(state.alert_threshold)},
            ),
            (
                "bradycardia",
                "rule",
                bool(state.is_bradycardia > 0.5),
                f"ברדיקרדיה (baseline={state.baseline_bpm:.0f} BPM)",
                {"baseline_bpm": float(state.baseline_bpm)},
            ),
            (
                "tachycardia",
                "rule",
                bool(state.is_tachycardia > 0.5),
                f"טכיקרדיה (baseline={state.baseline_bpm:.0f} BPM)",
                {"baseline_bpm": float(state.baseline_bpm)},
            ),
            (
                "low_variability",
                "rule",
                bool(state.variability_category <= 1.0),
                f"שונות נמוכה (קטגוריה {state.variability_category:.0f})",
                {"variability_category": float(state.variability_category)},
            ),
            (
                "sinusoidal",
                "rule",
                bool(state.sinusoidal_detected),
                "דפוס סינוסואידלי",
                {},
            ),
            (
                "tachysystole",
                "rule",
                bool(state.tachysystole_detected),
                "טכיסיסטולה",
                {},
            ),
        ]

        for event_type, source, condition, description, metadata in checks:
            if condition and event_type not in self._active:
                self._open_event(
                    event_type=event_type,
                    source=source,
                    sample=int(state.sample_count),
                    risk=float(state.risk_score),
                    top_contributions=top_contributions if source == "model" else [],
                    description=description,
                    metadata=metadata,
                )
            elif not condition and event_type in self._active:
                self._close_event(event_type, int(state.sample_count))
            elif condition and event_type in self._active:
                self._update_peak(
                    event_type=event_type,
                    sample=int(state.sample_count),
                    risk=float(state.risk_score),
                    top_contributions=top_contributions if source == "model" else [],
                )

        for interval in clinical_intervals:
            event_type = str(interval.get("event_type", ""))
            start_sample = int(interval.get("start_sample", state.sample_count))
            key = (event_type, start_sample)
            if not event_type or key in self._seen_deceleration_keys:
                continue
            self._seen_deceleration_keys.add(key)
            self._emit_interval_event(interval, float(state.risk_score))

    def flush_pending(self) -> list[DetectionEvent]:
        events = list(self._pending)
        self._pending.clear()
        return events

    def _open_event(
        self,
        event_type: str,
        source: str,
        sample: int,
        risk: float,
        top_contributions: list[FeatureContribution],
        description: str,
        metadata: dict[str, Any],
    ) -> None:
        event = DetectionEvent(
            event_id=uuid4().hex,
            bed_id=self._bed_id,
            source=source,
            event_type=event_type,
            start_sample=sample,
            end_sample=None,
            still_ongoing=True,
            peak_risk_score=risk,
            peak_sample=sample,
            top_contributions=list(top_contributions),
            description=description,
            timeline_summary=_timeline_summary(sample, None),
            metadata=dict(metadata),
        )
        self._active[event_type] = event
        self._pending.append(event)

    def _close_event(self, event_type: str, sample: int) -> None:
        event = self._active.pop(event_type)
        event.end_sample = sample
        event.still_ongoing = False
        event.timeline_summary = _timeline_summary(event.start_sample, event.end_sample)
        self._pending.append(event)

    def _update_peak(
        self,
        event_type: str,
        sample: int,
        risk: float,
        top_contributions: list[FeatureContribution],
    ) -> None:
        event = self._active[event_type]
        top_name_old = event.top_contributions[0].name if event.top_contributions else None
        top_name_new = top_contributions[0].name if top_contributions else None
        if risk > event.peak_risk_score:
            significant = risk - event.peak_risk_score > 0.05 or top_name_old != top_name_new
            event.peak_risk_score = risk
            event.peak_sample = sample
            if top_contributions:
                event.top_contributions = list(top_contributions)
            if significant:
                event.timeline_summary = _timeline_summary(event.start_sample, None)
                self._pending.append(event)

    def _emit_interval_event(self, interval: dict[str, Any], risk: float) -> None:
        event_type = str(interval["event_type"])
        start_sample = int(interval["start_sample"])
        end_sample = int(interval["end_sample"])
        depth = float(interval.get("depth_bpm", 0.0))

        labels = {
            "late_deceleration": "האטה מאוחרת",
            "variable_deceleration": "האטה משתנה",
            "prolonged_deceleration": "האטה ממושכת",
        }
        description = f"{labels.get(event_type, event_type)} בעומק {depth:.0f} BPM"
        event = DetectionEvent(
            event_id=uuid4().hex,
            bed_id=self._bed_id,
            source="rule",
            event_type=event_type,
            start_sample=start_sample,
            end_sample=end_sample,
            still_ongoing=False,
            peak_risk_score=risk,
            peak_sample=int(interval.get("nadir_sample", start_sample)),
            top_contributions=[],
            description=description,
            timeline_summary=_timeline_summary(start_sample, end_sample),
            metadata=dict(interval),
        )
        self._pending.append(event)

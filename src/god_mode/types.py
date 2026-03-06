"""
src/god_mode/types.py — God Mode data types
============================================

EventType:       9 injectable pathology types.
InjectionEvent:  Record of an active injection (feature override + signal swap).
EventAnnotation: Per-BedState summary sent to frontend via WebSocket.

PLAN.md references: §10.3, §10.7
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum


class EventType(str, Enum):
    LATE_DECELERATIONS     = "late_decelerations"
    VARIABLE_DECELERATIONS = "variable_decelerations"
    PROLONGED_DECELERATION = "prolonged_deceleration"
    SINUSOIDAL_PATTERN     = "sinusoidal_pattern"
    TACHYSYSTOLE           = "tachysystole"
    BRADYCARDIA            = "bradycardia"
    TACHYCARDIA            = "tachycardia"
    LOW_VARIABILITY        = "low_variability"
    COMBINED_SEVERE        = "combined_severe"


@dataclass
class InjectionEvent:
    """Record of a single God Mode injection."""

    event_id:     str
    bed_id:       str
    event_type:   EventType
    start_sample: int            # sample_count at injection time
    end_sample:   int | None     # None = ongoing (until manual stop)
    description:  str
    severity:     float          # 0.5–1.0
    created_at:   float = field(default_factory=time.time)

    # Signal swap tracking (god_mode_signal_plan.md)
    original_recording_id: str | None = None   # recording before swap — for restore
    signal_swapped: bool = False               # whether recording was swapped

    @classmethod
    def create(
        cls,
        bed_id: str,
        event_type: str | EventType,
        start_sample: int,
        duration_samples: int | None = None,
        severity: float = 0.85,
        description: str = "",
    ) -> "InjectionEvent":
        et = EventType(event_type)
        end = start_sample + duration_samples if duration_samples else None
        return cls(
            event_id=str(uuid.uuid4())[:8],
            bed_id=bed_id,
            event_type=et,
            start_sample=start_sample,
            end_sample=end,
            description=description or et.value,
            severity=severity,
        )


@dataclass
class EventAnnotation:
    """Summary of an active event, attached to BedState for the frontend."""

    event_id:         str
    event_type:       str
    start_sample:     int
    end_sample:       int | None
    still_ongoing:    bool
    description:      str
    timeline_summary: str           # "Started 00:12:34 | Duration: 00:03:20 | Ongoing"
    detected_details: dict          # {feature: value} overridden

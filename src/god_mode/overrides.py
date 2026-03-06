"""
src/god_mode/overrides.py — Feature override map per EventType
==============================================================

Clinical feature list order (matches CLINICAL_FEATURE_NAMES):
  [0] baseline_bpm
  [1] is_tachycardia
  [2] is_bradycardia
  [3] variability_amplitude_bpm
  [4] variability_category
  [5] n_late_decelerations
  [6] n_variable_decelerations
  [7] n_prolonged_decelerations
  [8] max_deceleration_depth_bpm
  [9] sinusoidal_detected
  [10] tachysystole_detected

PLAN.md reference: §10.5
"""

from __future__ import annotations

from src.god_mode.types import EventType, InjectionEvent


def build_feature_override(
    clin: list[float], event: InjectionEvent
) -> list[float]:
    """Return a new clin list with features elevated according to event_type.

    Only raises values, never lowers (additive overrides) — except for
    BRADYCARDIA (lowers baseline) and LOW_VARIABILITY (lowers amplitude).
    """
    out = list(clin)
    s = event.severity   # 0.5–1.0

    if event.event_type == EventType.LATE_DECELERATIONS:
        out[5] = max(out[5], round(3 + s * 4))     # n_late → 3–7
        out[8] = max(out[8], 15 + s * 20)           # depth → 15–35 bpm

    elif event.event_type == EventType.VARIABLE_DECELERATIONS:
        out[6] = max(out[6], round(3 + s * 5))     # n_variable → 3–8
        out[8] = max(out[8], 20 + s * 25)           # depth → 20–45 bpm

    elif event.event_type == EventType.PROLONGED_DECELERATION:
        out[7] = max(out[7], 1 + round(s))          # n_prolonged → 1–2
        out[8] = max(out[8], 30 + s * 20)           # depth → 30–50 bpm

    elif event.event_type == EventType.SINUSOIDAL_PATTERN:
        out[9] = 1.0                                 # sinusoidal_detected

    elif event.event_type == EventType.TACHYSYSTOLE:
        out[10] = 1.0                                # tachysystole_detected

    elif event.event_type == EventType.BRADYCARDIA:
        out[0] = min(out[0], 100 - s * 10)          # baseline → 90–100 bpm
        out[2] = 1.0                                 # is_bradycardia

    elif event.event_type == EventType.TACHYCARDIA:
        out[0] = max(out[0], 165 + s * 15)          # baseline → 165–180 bpm
        out[1] = 1.0                                 # is_tachycardia

    elif event.event_type == EventType.LOW_VARIABILITY:
        out[3] = min(out[3], max(0.5, 2 - s * 1.5)) # amplitude → 0.5–2 bpm
        out[4] = 0.0                                 # category = absent

    elif event.event_type == EventType.COMBINED_SEVERE:
        out[5]  = max(out[5], 3)                     # late decels
        out[7]  = max(out[7], 1)                     # prolonged
        out[8]  = max(out[8], 40.0)                  # depth
        out[3]  = min(out[3], 2.0)                   # low variability
        out[4]  = 0.0                                # category absent
        out[10] = 1.0                                # tachysystole

    return out

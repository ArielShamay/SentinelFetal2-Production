"""Feature-level explainability for the LogisticRegression risk scorer.

The final Sentinel risk score is produced by a linear logistic model over the
25-feature vector.  For such a model, the exact per-feature logit contribution
is simply:

    scaled_feature_value * coefficient

This module exposes that contribution without changing the trained artifacts.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import log
from typing import Any, Sequence

import numpy as np


@dataclass
class FeatureContribution:
    """Contribution of one feature to the LR logit."""

    name: str
    friendly_label: str
    raw_value: float
    scaled_value: float
    coefficient: float
    contribution: float
    direction: str


FRIENDLY_LABELS: dict[str, dict[str, str]] = {
    "segment_length": {"he": "משך סגמנט התרעה", "en": "Alert segment length"},
    "max_prediction": {"he": "הסתברות מקסימלית בסגמנט", "en": "Max segment prediction"},
    "cumulative_sum": {"he": "סכום מצטבר של הסתברויות", "en": "Cumulative probability sum"},
    "weighted_integral": {"he": "אינטגרל משוקלל מעל הסף", "en": "Weighted integral above threshold"},
    "n_alert_segments": {"he": "מספר סגמנטים חשודים", "en": "Number of alert segments"},
    "alert_fraction": {"he": "חלק יחסי של חלונות חשודים", "en": "Alert window fraction"},
    "mean_prediction": {"he": "הסתברות ממוצעת בסגמנט", "en": "Mean segment prediction"},
    "std_prediction": {"he": "שונות הסתברויות בסגמנט", "en": "Segment prediction variability"},
    "max_pred_all_segments": {"he": "הסתברות מקסימלית בכל הסגמנטים", "en": "Max prediction across segments"},
    "total_alert_duration": {"he": "משך מצטבר של סגמנטים חשודים", "en": "Total alert duration"},
    "recording_max_score": {"he": "ציון מקסימלי בהקלטה", "en": "Recording max score"},
    "recording_mean_above_th": {"he": "ממוצע ציונים מעל הסף", "en": "Mean score above threshold"},
    "baseline_bpm": {"he": "דופק בסיסי", "en": "Baseline heart rate"},
    "is_tachycardia": {"he": "טכיקרדיה", "en": "Tachycardia"},
    "is_bradycardia": {"he": "ברדיקרדיה", "en": "Bradycardia"},
    "variability_amplitude_bpm": {"he": "אמפליטודת שונות", "en": "Variability amplitude"},
    "variability_category": {"he": "קטגוריית שונות", "en": "Variability category"},
    "n_late_decelerations": {"he": "האטות מאוחרות", "en": "Late decelerations"},
    "n_variable_decelerations": {"he": "האטות משתנות", "en": "Variable decelerations"},
    "n_prolonged_decelerations": {"he": "האטות ממושכות", "en": "Prolonged decelerations"},
    "max_deceleration_depth_bpm": {"he": "עומק האטה מקסימלי", "en": "Max deceleration depth"},
    "sinusoidal_detected": {"he": "דפוס סינוסואידלי", "en": "Sinusoidal pattern"},
    "tachysystole_detected": {"he": "טכיסיסטולה", "en": "Tachysystole"},
    "overall_mean_prob": {"he": "ממוצע הסתברות כללי", "en": "Overall mean probability"},
    "overall_std_prob": {"he": "שונות הסתברות כללית", "en": "Overall probability variability"},
}


def compute_top_contributions(
    x_raw: Sequence[float] | np.ndarray,
    x_scaled: Sequence[float] | np.ndarray,
    lr: Any,
    feature_names: Sequence[str],
    top_k: int = 5,
) -> list[FeatureContribution]:
    """Return the largest absolute LR logit contributions."""

    raw = np.asarray(x_raw, dtype=np.float64).reshape(-1)
    scaled = np.asarray(x_scaled, dtype=np.float64).reshape(-1)
    coef = np.asarray(lr.coef_[0], dtype=np.float64).reshape(-1)
    names = list(feature_names)

    if not (len(raw) == len(scaled) == len(coef) == len(names)):
        raise ValueError(
            "Feature vector, scaled vector, coefficients, and feature_names "
            f"must have equal length; got raw={len(raw)}, scaled={len(scaled)}, "
            f"coef={len(coef)}, names={len(names)}"
        )

    items: list[FeatureContribution] = []
    for idx, name in enumerate(names):
        contribution = float(scaled[idx] * coef[idx])
        labels = FRIENDLY_LABELS.get(name, {"he": name, "en": name})
        items.append(
            FeatureContribution(
                name=name,
                friendly_label=labels["he"],
                raw_value=float(raw[idx]),
                scaled_value=float(scaled[idx]),
                coefficient=float(coef[idx]),
                contribution=contribution,
                direction="increases_risk" if contribution > 0 else "decreases_risk",
            )
        )

    return sorted(items, key=lambda item: abs(item.contribution), reverse=True)[:top_k]


def assert_logit_consistency(x_scaled: Sequence[float] | np.ndarray, lr: Any, tol: float = 1e-6) -> None:
    """Sanity-check that manual logit math matches sklearn predict_proba."""

    scaled = np.asarray(x_scaled, dtype=np.float64).reshape(1, -1)
    manual_logit = float(np.dot(scaled[0], lr.coef_[0]) + lr.intercept_[0])
    prob = float(lr.predict_proba(scaled)[0, 1])
    predicted_logit = log(prob / (1.0 - prob))
    if abs(manual_logit - predicted_logit) > tol:
        raise AssertionError(
            f"LR logit mismatch: manual={manual_logit}, predict_proba={predicted_logit}"
        )

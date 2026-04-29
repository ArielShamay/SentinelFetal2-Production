"""
src/features/clinical_extractor.py — Clinical Feature Extractor
================================================================
Coordinates all 5 rule modules to produce 11 clinical features per recording.

These 11 features are appended AFTER the 12 PatchTST anomaly features in
extract_features_for_split() to form the 23-feature input for the LR classifier.

Feature ordering (must be stable — corresponds to columns 12-22 of X matrix):
    13. baseline_bpm
    14. is_tachycardia
    15. is_bradycardia
    16. variability_amplitude_bpm
    17. variability_category
    18. n_late_decelerations
    19. n_variable_decelerations
    20. n_prolonged_decelerations
    21. max_deceleration_depth_bpm
    22. sinusoidal_detected
    23. tachysystole_detected

Input:  signal (np.ndarray, shape (2, T)) — normalized, FHR∈[0,1], UC∈[0,1], 4 Hz
Output: List[float] of length N_CLINICAL_FEATURES in the order above
"""

from __future__ import annotations

import logging
from typing import Any, List

import numpy as np

from src.rules.baseline     import calculate_baseline,          BaselineResult
from src.rules.variability  import calculate_variability,       VariabilityResult
from src.rules.decelerations import detect_decelerations,       DecelerationSummary
from src.rules.sinusoidal   import detect_sinusoidal_pattern,   SinusoidalResult
from src.rules.tachysystole import detect_tachysystole,         TachysystoleResult

log = logging.getLogger(__name__)

# ── Public constants ─────────────────────────────────────────────────────────

CLINICAL_FEATURE_NAMES: List[str] = [
    "baseline_bpm",
    "is_tachycardia",
    "is_bradycardia",
    "variability_amplitude_bpm",
    "variability_category",
    "n_late_decelerations",
    "n_variable_decelerations",
    "n_prolonged_decelerations",
    "max_deceleration_depth_bpm",
    "sinusoidal_detected",
    "tachysystole_detected",
]

N_CLINICAL_FEATURES: int = len(CLINICAL_FEATURE_NAMES)  # 11

# Safe defaults — returned when a module fails or signal is degenerate
SAFE_DEFAULTS: dict[str, float] = {
    "baseline_bpm":               130.0,   # midpoint of normal range
    "is_tachycardia":             0.0,
    "is_bradycardia":             0.0,
    "variability_amplitude_bpm":  15.0,    # midpoint of moderate range
    "variability_category":       2.0,     # moderate (normal)
    "n_late_decelerations":       0.0,
    "n_variable_decelerations":   0.0,
    "n_prolonged_decelerations":  0.0,
    "max_deceleration_depth_bpm": 0.0,
    "sinusoidal_detected":        0.0,
    "tachysystole_detected":      0.0,
}

assert list(SAFE_DEFAULTS.keys()) == CLINICAL_FEATURE_NAMES, (
    "BUG: SAFE_DEFAULTS keys must match CLINICAL_FEATURE_NAMES in order"
)


# ── Denormalization ──────────────────────────────────────────────────────────

def _denormalize(signal_normalized: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Convert normalized signal (2, T) back to physical units.

    .npy files use:
      FHR: (fhr_bpm - 50) / 160  →  reverse: fhr_bpm = sig * 160 + 50
      UC:  uc_mmhg / 100         →  reverse: uc_mmhg = sig * 100
    """
    fhr = signal_normalized[0] * 160.0 + 50.0   # → [50, 210] bpm
    uc  = signal_normalized[1] * 100.0           # → [0, 100] mmHg
    return fhr, uc


# ── Main function ────────────────────────────────────────────────────────────

def extract_clinical_features(
    signal_normalized: np.ndarray,
    fs: float = 4.0,
) -> List[float]:
    """Extract 11 clinical features from a normalized CTG signal.

    Args:
        signal_normalized: shape (2, T), FHR channel 0 ∈ [0,1], UC channel 1 ∈ [0,1].
        fs:                Sampling frequency in Hz (default 4.0).

    Returns:
        List of 11 floats in CLINICAL_FEATURE_NAMES order.
        Returns SAFE_DEFAULTS values if the signal is degenerate or any module fails.
    """
    feats: dict[str, float] = dict(SAFE_DEFAULTS)  # start with defaults

    try:
        signal_normalized = np.asarray(signal_normalized, dtype=float)
        if signal_normalized.ndim != 2 or signal_normalized.shape[0] < 2:
            return [feats[k] for k in CLINICAL_FEATURE_NAMES]

        fhr, uc = _denormalize(signal_normalized)

        # Replace NaN in FHR with a midrange value before passing to rules
        fhr_safe = np.nan_to_num(fhr, nan=130.0)
        uc_safe  = np.nan_to_num(uc,  nan=0.0)

    except Exception as exc:
        log.warning(f"[clinical_extractor] Denormalization failed: {exc}")
        return [feats[k] for k in CLINICAL_FEATURE_NAMES]

    # ── Baseline ──────────────────────────────────────────────────────────────
    try:
        b: BaselineResult = calculate_baseline(fhr_safe, fs=fs)
        feats["baseline_bpm"]   = b.baseline_bpm
        feats["is_tachycardia"] = b.is_tachycardia
        feats["is_bradycardia"] = b.is_bradycardia
    except Exception as exc:
        log.warning(f"[clinical_extractor] Baseline module failed: {exc}")

    # ── Variability ───────────────────────────────────────────────────────────
    try:
        v: VariabilityResult = calculate_variability(fhr_safe, fs=fs)
        feats["variability_amplitude_bpm"] = v.amplitude_bpm
        feats["variability_category"]      = v.category
    except Exception as exc:
        log.warning(f"[clinical_extractor] Variability module failed: {exc}")

    # ── Decelerations ─────────────────────────────────────────────────────────
    try:
        d: DecelerationSummary = detect_decelerations(fhr_safe, uc_safe, fs=fs)
        feats["n_late_decelerations"]       = d.n_late_decelerations
        feats["n_variable_decelerations"]   = d.n_variable_decelerations
        feats["n_prolonged_decelerations"]  = d.n_prolonged_decelerations
        feats["max_deceleration_depth_bpm"] = d.max_deceleration_depth_bpm
    except Exception as exc:
        log.warning(f"[clinical_extractor] Decelerations module failed: {exc}")

    # ── Sinusoidal ────────────────────────────────────────────────────────────
    try:
        s: SinusoidalResult = detect_sinusoidal_pattern(fhr_safe, fs=fs)
        feats["sinusoidal_detected"] = s.sinusoidal_detected
    except Exception as exc:
        log.warning(f"[clinical_extractor] Sinusoidal module failed: {exc}")

    # ── Tachysystole ──────────────────────────────────────────────────────────
    try:
        t: TachysystoleResult = detect_tachysystole(uc_safe, fs=fs)
        feats["tachysystole_detected"] = t.tachysystole_detected
    except Exception as exc:
        log.warning(f"[clinical_extractor] Tachysystole module failed: {exc}")

    return [feats[k] for k in CLINICAL_FEATURE_NAMES]


def extract_clinical_features_with_intervals(
    signal_normalized: np.ndarray,
    fs: float = 4.0,
    sample_offset: int = 0,
) -> dict[str, Any]:
    """Extract clinical features and time-bounded rule intervals.

    This is the explainability-friendly API used by the real-time pipeline.
    The legacy extract_clinical_features() function remains list-compatible
    for scripts/tests that only need the 11 scalar features.
    """

    feats: dict[str, float] = dict(SAFE_DEFAULTS)
    intervals: list[dict[str, Any]] = []

    try:
        signal_normalized = np.asarray(signal_normalized, dtype=float)
        if signal_normalized.ndim != 2 or signal_normalized.shape[0] < 2:
            return {
                "features": [feats[k] for k in CLINICAL_FEATURE_NAMES],
                "intervals": intervals,
            }

        fhr, uc = _denormalize(signal_normalized)
        fhr_safe = np.nan_to_num(fhr, nan=130.0)
        uc_safe = np.nan_to_num(uc, nan=0.0)

    except Exception as exc:
        log.warning(f"[clinical_extractor] Denormalization failed: {exc}")
        return {
            "features": [feats[k] for k in CLINICAL_FEATURE_NAMES],
            "intervals": intervals,
        }

    try:
        b: BaselineResult = calculate_baseline(fhr_safe, fs=fs)
        feats["baseline_bpm"] = b.baseline_bpm
        feats["is_tachycardia"] = b.is_tachycardia
        feats["is_bradycardia"] = b.is_bradycardia
    except Exception as exc:
        log.warning(f"[clinical_extractor] Baseline module failed: {exc}")

    try:
        v: VariabilityResult = calculate_variability(fhr_safe, fs=fs)
        feats["variability_amplitude_bpm"] = v.amplitude_bpm
        feats["variability_category"] = v.category
    except Exception as exc:
        log.warning(f"[clinical_extractor] Variability module failed: {exc}")

    try:
        d: DecelerationSummary = detect_decelerations(
            fhr_safe,
            uc_safe,
            fs=fs,
            sample_offset=sample_offset,
        )
        feats["n_late_decelerations"] = d.n_late_decelerations
        feats["n_variable_decelerations"] = d.n_variable_decelerations
        feats["n_prolonged_decelerations"] = d.n_prolonged_decelerations
        feats["max_deceleration_depth_bpm"] = d.max_deceleration_depth_bpm
        intervals.extend(d.intervals or [])
    except Exception as exc:
        log.warning(f"[clinical_extractor] Decelerations module failed: {exc}")

    try:
        s: SinusoidalResult = detect_sinusoidal_pattern(fhr_safe, fs=fs)
        feats["sinusoidal_detected"] = s.sinusoidal_detected
    except Exception as exc:
        log.warning(f"[clinical_extractor] Sinusoidal module failed: {exc}")

    try:
        t: TachysystoleResult = detect_tachysystole(uc_safe, fs=fs)
        feats["tachysystole_detected"] = t.tachysystole_detected
    except Exception as exc:
        log.warning(f"[clinical_extractor] Tachysystole module failed: {exc}")

    return {
        "features": [feats[k] for k in CLINICAL_FEATURE_NAMES],
        "intervals": intervals,
    }

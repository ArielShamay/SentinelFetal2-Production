"""
src/rules/baseline.py — FHR Baseline Calculator
================================================
Ported from github.com/ArielShamay/SentinelFetal (stripped of API/framework deps).

Algorithm (Israeli Position Paper / ACOG standard):
- Sliding 2-minute windows (50% overlap)
- Stable window: variability (max-min) < 25 bpm AND ≥80% non-NaN values
- Baseline = mean of all stable windows, rounded to nearest 5 bpm
- Fallback: global median if no stable window found
- Classification: tachycardia >160 bpm, bradycardia <110 bpm

Input:  fhr (np.ndarray, shape (T,)) — raw FHR in bpm, 4 Hz
Output: BaselineResult dataclass
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import numpy as np

log = logging.getLogger(__name__)

# Clinical thresholds (Israeli Position Paper)
TACHYCARDIA_THRESHOLD  = 160.0   # bpm
BRADYCARDIA_THRESHOLD  = 110.0   # bpm
VARIABILITY_MAX_STABLE = 25.0    # bpm — max variability for a "stable" window
MIN_VALID_FRACTION     = 0.80    # fraction of non-NaN samples required per window

# Defaults used as fallback when signal quality is too poor
BASELINE_SAFE_DEFAULT  = 130.0   # bpm — midpoint of normal range


@dataclass
class BaselineResult:
    baseline_bpm:    float = BASELINE_SAFE_DEFAULT
    is_tachycardia:  float = 0.0   # 1.0 if baseline > 160 bpm
    is_bradycardia:  float = 0.0   # 1.0 if baseline < 110 bpm
    confidence:      float = 0.0   # 0–1; 0 = fallback used


def _round_to_nearest_5(value: float) -> float:
    """Round to nearest 5 bpm increment (ACOG standard)."""
    return float(round(value / 5.0) * 5.0)


def calculate_baseline(
    fhr: np.ndarray,
    fs: float = 4.0,
    window_min: float = 2.0,
    overlap: float = 0.5,
) -> BaselineResult:
    """Calculate FHR baseline using stable-segment sliding window.

    Args:
        fhr:        FHR signal in bpm, shape (T,). Values should be ~50–210 bpm.
        fs:         Sampling frequency in Hz (default 4.0).
        window_min: Window duration in minutes (default 2.0).
        overlap:    Fractional overlap between windows (default 0.5 = 50%).

    Returns:
        BaselineResult with baseline_bpm, is_tachycardia, is_bradycardia, confidence.
    """
    try:
        fhr = np.asarray(fhr, dtype=float)
        if fhr.ndim != 1 or len(fhr) == 0:
            return BaselineResult()

        window_samples = int(window_min * 60 * fs)
        stride_samples = max(1, int(window_samples * (1 - overlap)))

        stable_means: list[float] = []

        for start in range(0, len(fhr) - window_samples + 1, stride_samples):
            window = fhr[start : start + window_samples]
            valid  = window[~np.isnan(window)]

            # Require minimum valid fraction
            if len(valid) < MIN_VALID_FRACTION * window_samples:
                continue

            variability = float(np.max(valid) - np.min(valid))
            if variability < VARIABILITY_MAX_STABLE:
                stable_means.append(float(np.mean(valid)))

        if stable_means:
            raw_baseline = float(np.mean(stable_means))
            confidence   = min(1.0, len(stable_means) / 5.0)
        else:
            # Fallback: global median of valid samples
            valid_all = fhr[~np.isnan(fhr)]
            if len(valid_all) == 0:
                return BaselineResult()
            raw_baseline = float(np.median(valid_all))
            confidence   = 0.0

        baseline = _round_to_nearest_5(raw_baseline)
        baseline = float(np.clip(baseline, 50.0, 210.0))

        return BaselineResult(
            baseline_bpm   = baseline,
            is_tachycardia = 1.0 if baseline > TACHYCARDIA_THRESHOLD else 0.0,
            is_bradycardia = 1.0 if baseline < BRADYCARDIA_THRESHOLD else 0.0,
            confidence     = confidence,
        )

    except Exception as exc:
        log.warning(f"[baseline] Failed: {exc}. Returning safe defaults.")
        return BaselineResult()

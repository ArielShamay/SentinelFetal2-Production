"""
src/rules/variability.py — FHR Variability Calculator
======================================================
Ported from github.com/ArielShamay/SentinelFetal (stripped of API/framework deps).

Algorithm (Israeli Position Paper / ACOG standard):
- 1-minute windows with 50% overlap
- Only BASELINE windows (FHR near stable level) are included — deceleration
  windows are excluded so that dip depth is not confused with variability
- Amplitude per window = max - min of valid samples in window
- Mean amplitude across all baseline windows = variability estimate
- Classification into 4 categories (absent/minimal/moderate/marked)

Key fix (v8.1): The original code used max-min over ALL windows, including
those that contain deceleration dips. A window whose FHR spans 130→90 bpm
gets amplitude=40 bpm even though variability is normal. This caused Acidemia
cases (more decelerations) to appear as "marked variability", reversing the
clinical direction of the feature.

Fix: estimate a global stable FHR reference (90th percentile), then exclude
any window whose median falls more than DECEL_EXCLUSION_BPM below that
reference. Fall back to full-signal P90-P10 range if too few windows survive.

Input:  fhr (np.ndarray, shape (T,)) — raw FHR in bpm, 4 Hz
Output: VariabilityResult dataclass
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np

log = logging.getLogger(__name__)

# Variability category boundaries (bpm)
ABSENT_MAX   = 2.0    # ≤2 bpm   → absent   (0)
MINIMAL_MAX  = 5.0    # 3–5 bpm  → minimal  (1)
MODERATE_MAX = 25.0   # 6–25 bpm → moderate (2), >25 → marked (3)

# Safe defaults (middle of moderate range)
VARIABILITY_SAFE_AMPLITUDE = 15.0
VARIABILITY_SAFE_CATEGORY  = 2

# Window filtering: exclude windows that are inside decelerations.
# A window whose median is more than this many bpm below the reference baseline
# is considered a deceleration window and skipped.
DECEL_EXCLUSION_BPM = 15.0    # bpm below reference to exclude window
BASELINE_REF_PCTILE = 90.0    # percentile for estimating stable FHR level
MIN_BASELINE_WINDOWS = 3      # if fewer survive filtering, use fallback


@dataclass
class VariabilityResult:
    amplitude_bpm: float = VARIABILITY_SAFE_AMPLITUDE
    category:      float = float(VARIABILITY_SAFE_CATEGORY)  # 0/1/2/3 as float for LR


def _categorize(amplitude: float) -> float:
    if amplitude <= ABSENT_MAX:
        return 0.0   # absent
    elif amplitude <= MINIMAL_MAX:
        return 1.0   # minimal
    elif amplitude <= MODERATE_MAX:
        return 2.0   # moderate
    else:
        return 3.0   # marked


def calculate_variability(
    fhr: np.ndarray,
    fs: float = 4.0,
    window_min: float = 1.0,
    overlap: float = 0.5,
) -> VariabilityResult:
    """Calculate FHR variability using overlapping 1-minute baseline windows.

    Only windows where the FHR is near the stable baseline level are included.
    Windows that fall inside decelerations are excluded before computing
    the amplitude estimate.

    Args:
        fhr:        FHR signal in bpm, shape (T,).
        fs:         Sampling frequency in Hz (default 4.0).
        window_min: Window duration in minutes (default 1.0).
        overlap:    Fractional overlap (default 0.5 = 50%).

    Returns:
        VariabilityResult with amplitude_bpm and category.
    """
    try:
        fhr = np.asarray(fhr, dtype=float)
        if fhr.ndim != 1 or len(fhr) == 0:
            return VariabilityResult()

        window_samples = int(window_min * 60 * fs)
        stride_samples = max(1, int(window_samples * (1 - overlap)))

        # Stable-FHR reference: 90th percentile of the full trace.
        # Represents the FHR level during quiescent (non-deceleration) periods.
        valid_all = fhr[~np.isnan(fhr)]
        if len(valid_all) == 0:
            return VariabilityResult()
        ref_level = float(np.percentile(valid_all, BASELINE_REF_PCTILE))

        # Threshold below which a window is flagged as "inside a deceleration"
        exclusion_threshold = ref_level - DECEL_EXCLUSION_BPM

        amplitudes: list[float] = []

        for start in range(0, len(fhr) - window_samples + 1, stride_samples):
            window = fhr[start : start + window_samples]
            valid  = window[~np.isnan(window)]

            if len(valid) < window_samples * 0.5:   # require ≥50% valid
                continue

            # Skip windows whose median is deep inside a deceleration
            if float(np.median(valid)) < exclusion_threshold:
                continue

            amplitudes.append(float(np.max(valid) - np.min(valid)))

        # Fallback: if too few baseline windows survived, use P90-P10 on
        # the full signal's upper range (still robust vs full max-min)
        if len(amplitudes) < MIN_BASELINE_WINDOWS:
            log.debug("[variability] Too few baseline windows — using P90-P10 fallback")
            p90 = float(np.percentile(valid_all, 90))
            p10 = float(np.percentile(valid_all, 10))
            mean_amplitude = p90 - p10
        else:
            mean_amplitude = float(np.mean(amplitudes))

        return VariabilityResult(
            amplitude_bpm = mean_amplitude,
            category      = _categorize(mean_amplitude),
        )

    except Exception as exc:
        log.warning(f"[variability] Failed: {exc}. Returning safe defaults.")
        return VariabilityResult()

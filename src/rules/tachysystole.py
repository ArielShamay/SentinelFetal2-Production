"""
src/rules/tachysystole.py — Uterine Tachysystole Detector
==========================================================
Ported from github.com/ArielShamay/SentinelFetal (stripped of API/framework deps).

Algorithm (Israeli Position Paper):
- Tachysystole: >5 contractions per 10 minutes, averaged over 30-minute window
- Peak detection via scipy.signal.find_peaks on UC signal
- Min contraction spacing: 60 seconds

Input:  uc (T,) — raw UC signal in mmHg, 4 Hz
Output: TachysystoleResult dataclass
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
from scipy.signal import find_peaks

log = logging.getLogger(__name__)

# Thresholds
MAX_CONTRACTIONS_PER_10MIN = 5.0    # tachysystole threshold
ANALYSIS_WINDOW_MIN        = 30.0   # minutes of signal to analyse
MIN_PEAK_SPACING_S         = 60.0   # minimum 60 s between contractions

# Absolute contraction detection thresholds (mmHg).
# The original code used the 75th-percentile value as a relative prominence
# threshold, which fails when the UC baseline is near zero (over-detection)
# or when contractions are all similar height (under-detection).
# An absolute floor is more stable across recordings.
MIN_UC_PROMINENCE_MMHG  = 10.0   # minimum prominence above local baseline
MIN_UC_HEIGHT_MMHG      =  8.0   # minimum peak height above zero


@dataclass
class TachysystoleResult:
    tachysystole_detected:      float = 0.0   # 0.0 or 1.0
    contractions_per_10min:     float = 0.0
    n_contractions_in_window:   float = 0.0


def detect_tachysystole(
    uc: np.ndarray,
    fs: float = 4.0,
) -> TachysystoleResult:
    """Detect uterine tachysystole from UC signal.

    Args:
        uc:  UC signal in mmHg, shape (T,).
        fs:  Sampling frequency in Hz (default 4.0).

    Returns:
        TachysystoleResult with tachysystole_detected, contractions_per_10min.
    """
    try:
        uc = np.asarray(uc, dtype=float)
        uc = np.nan_to_num(uc, nan=0.0)

        # Use last ANALYSIS_WINDOW_MIN of signal (most clinically relevant)
        analysis_samples = int(ANALYSIS_WINDOW_MIN * 60 * fs)
        if len(uc) > analysis_samples:
            uc_window = uc[-analysis_samples:]
        else:
            uc_window = uc

        if len(uc_window) < int(30 * fs):
            return TachysystoleResult()

        window_min  = len(uc_window) / (60.0 * fs)
        min_spacing = int(MIN_PEAK_SPACING_S * fs)

        peaks, _ = find_peaks(
            uc_window,
            distance   = min_spacing,
            prominence = MIN_UC_PROMINENCE_MMHG,
            height     = MIN_UC_HEIGHT_MMHG,
        )

        n_contractions = len(peaks)

        if window_min > 0:
            contractions_per_10min = n_contractions / (window_min / 10.0)
        else:
            contractions_per_10min = 0.0

        detected = contractions_per_10min > MAX_CONTRACTIONS_PER_10MIN

        return TachysystoleResult(
            tachysystole_detected    = 1.0 if detected else 0.0,
            contractions_per_10min   = contractions_per_10min,
            n_contractions_in_window = float(n_contractions),
        )

    except Exception as exc:
        log.warning(f"[tachysystole] Failed: {exc}. Returning safe defaults.")
        return TachysystoleResult()

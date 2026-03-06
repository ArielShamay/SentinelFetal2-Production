"""
src/rules/decelerations.py — FHR Deceleration Detector
=======================================================
Ported from github.com/ArielShamay/SentinelFetal (stripped of API/framework deps).

Definitions (Israeli Position Paper / ACOG / FIGO):
- Deceleration: FHR drop ≥15 bpm below baseline, lasting ≥15 seconds
- Early:     gradual onset (true onset-to-nadir ≥30s), nadir ≤15s after UC peak
- Late:      gradual onset (true onset-to-nadir ≥30s), nadir >15s after UC peak
- Variable:  abrupt onset (true onset-to-nadir <30s)
- Prolonged: duration ≥2 minutes (120s)

Detection pipeline:
1. Compute baseline (rolling median of stable 2-min segments)
2. Find dip events: FHR < baseline - 15 bpm for ≥15 seconds
3. For each dip, walk back to TRUE onset (last sample near baseline before threshold
   crossing) → compute true onset-to-nadir time → classify abrupt vs gradual
4. Use UC signal to classify gradual events as late vs early
5. Separate prolonged events (≥2 min) from shorter ones

Key fix (v8.1): The original code measured descent time from `event_start`
(the threshold-crossing point, already 15 bpm into the drop) to nadir.
This systematically under-estimated descent time and caused gradual LATE
decelerations to be misclassified as VARIABLE. We now walk backwards to find
the TRUE onset before the threshold was crossed.

Input:  fhr (T,), uc (T,) — raw signals in bpm / mmHg, 4 Hz
Output: DecelerationSummary dataclass
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List, Optional, Tuple

import numpy as np
from scipy.signal import find_peaks

log = logging.getLogger(__name__)

# ── Thresholds (Israeli Position Paper / ACOG) ───────────────────────────────
MIN_DEPTH_BPM    = 15.0    # bpm below baseline to qualify as a deceleration
MIN_DURATION_S   = 15.0    # minimum event duration (seconds)
PROLONGED_MIN_S  = 120.0   # prolonged deceleration threshold (2 minutes)
VARIABLE_ONSET_S = 30.0    # true onset-to-nadir < 30s → abrupt → variable
LATE_NADIR_LAG_S = 15.0    # nadir > 15s after UC peak → late

ROLLING_WINDOW_S = 120.0   # rolling baseline window (2 min)

# Global baseline floor: prevents the rolling median from collapsing into a
# prolonged deceleration valley. We compute the 85th-percentile of the
# entire FHR signal as the "stable level" and floor the rolling baseline at
# (stable_level - 20 bpm). This has no effect on normal/short events where
# the rolling median stays near the true baseline.
BASELINE_STABLE_PCTILE    = 85.0   # percentile for global stable-FHR estimate
BASELINE_FLOOR_DROP_BPM   = 20.0   # max allowed drop of baseline below that estimate

# Onset lookback: how far before threshold-crossing to search for true onset
TRUE_ONSET_LOOKBACK_S = 60.0    # seconds
TRUE_ONSET_MARGIN_BPM =  5.0    # FHR within this margin of baseline = "at baseline"

# UC peak detection: lower prominence captures subtle contractions in CTU-UHB
UC_PEAK_PROMINENCE   =  2.0    # mmHg  (was 5.0 — too strict for many signals)
UC_SEARCH_WINDOW_S   = 90.0    # ±seconds around event (was 60 — expanded)


@dataclass
class DecelerationSummary:
    n_late_decelerations:      float = 0.0
    n_variable_decelerations:  float = 0.0
    n_prolonged_decelerations: float = 0.0
    max_deceleration_depth_bpm: float = 0.0


# ── Helpers ───────────────────────────────────────────────────────────────────

def _compute_rolling_baseline(fhr: np.ndarray, fs: float, window_s: float) -> np.ndarray:
    """Rolling median baseline — approximates the stable FHR without decelerations.

    Two-pass strategy:
    1. Symmetric rolling median (fast, well-behaved for short events).
    2. Global floor: clamp baseline to (global_85th_pct - BASELINE_FLOOR_DROP_BPM)
       so that prolonged decelerations don't cause the rolling median to collapse
       into the event valley and lose sensitivity.
    """
    win = max(1, int(window_s * fs))
    n = len(fhr)
    baseline = np.empty(n)
    baseline[:] = np.nan
    half = win // 2
    for i in range(n):
        lo = max(0, i - half)
        hi = min(n, i + half + 1)
        seg = fhr[lo:hi]
        valid = seg[~np.isnan(seg)]
        if len(valid) > 0:
            baseline[i] = np.median(valid)
    valid_all = fhr[~np.isnan(fhr)]
    global_med = float(np.median(valid_all)) if len(valid_all) > 0 else 130.0
    baseline = np.where(np.isnan(baseline), global_med, baseline)

    # Global floor: prevents collapse into prolonged deceleration valleys
    if len(valid_all) > 0:
        global_stable = float(np.percentile(valid_all, BASELINE_STABLE_PCTILE))
        floor_value   = global_stable - BASELINE_FLOOR_DROP_BPM
        baseline      = np.maximum(baseline, floor_value)

    return baseline


def _find_dip_events(
    fhr: np.ndarray,
    baseline: np.ndarray,
    fs: float,
) -> List[Tuple[int, int]]:
    """Find contiguous segments where FHR < baseline - MIN_DEPTH_BPM.

    Returns list of (start_idx, end_idx) pairs where end_idx is exclusive.
    Only includes events lasting ≥ MIN_DURATION_S seconds.
    """
    min_dur_samples = int(MIN_DURATION_S * fs)
    below = fhr < (baseline - MIN_DEPTH_BPM)

    events: List[Tuple[int, int]] = []
    in_event = False
    start = 0
    for i in range(len(below)):
        if below[i] and not in_event:
            in_event = True
            start = i
        elif not below[i] and in_event:
            in_event = False
            if (i - start) >= min_dur_samples:
                events.append((start, i))
    if in_event and (len(below) - start) >= min_dur_samples:
        events.append((start, len(below)))

    return events


def _true_onset_idx(
    fhr: np.ndarray,
    baseline: np.ndarray,
    event_start: int,
    fs: float,
) -> int:
    """Find the true FHR descent onset BEFORE the threshold-crossing point.

    The detection threshold (baseline - 15 bpm) is crossed only after the FHR
    has already been descending for some time.  This function walks BACKWARD
    from event_start to find the last sample where FHR was still near the
    pre-event stable level.

    IMPORTANT: We do NOT use the rolling `baseline` array for the threshold
    here, because that baseline is computed over a symmetric window that
    INCLUDES the deceleration valley — pulling the estimate down and causing
    the onset search to miss the true start of the drop.

    Instead we estimate the pre-event stable FHR from the upper quartile of
    the lookback window (samples before event_start).  This is robust even
    when the FHR has been gradually descending for a while before crossing
    the detection threshold.

    Returns the index of the true onset (≤ event_start).
    """
    lookback = max(0, event_start - int(TRUE_ONSET_LOOKBACK_S * fs))

    # Stable pre-event FHR: upper quartile of the lookback window.
    # Using Q75 rather than median/max so that artifacts and brief dips
    # before the event don't inflate the reference upward.
    pre_window = fhr[lookback:event_start]
    if len(pre_window) >= int(5 * fs):   # need at least 5 s of data
        stable_ref = float(np.percentile(pre_window, 75))
    else:
        # Not enough pre-event data — fall back to the rolling baseline
        stable_ref = float(baseline[max(0, event_start - 1)])

    # Ensure the reference is physiologically plausible (≥ 100 bpm)
    stable_ref = max(stable_ref, 100.0)
    threshold  = stable_ref - TRUE_ONSET_MARGIN_BPM

    # Walk backwards: find the last sample still at/near the stable FHR
    for i in range(event_start - 1, lookback - 1, -1):
        if fhr[i] >= threshold:
            return i

    # Fallback: return the boundary of the lookback window
    return lookback


def _find_nearest_uc_peak(
    uc: np.ndarray,
    event_start: int,
    event_end: int,
    fs: float,
) -> Optional[int]:
    """Find the UC peak index nearest to the deceleration event.

    Returns the absolute index of the nearest peak, or None if no peak found.
    Returning None (instead of a fallback sentinel) lets the caller decide how
    to handle the ambiguous case, avoiding false late-deceleration labels.
    """
    search_lo = max(0, event_start - int(UC_SEARCH_WINDOW_S * fs))
    search_hi = min(len(uc), event_end  + int(UC_SEARCH_WINDOW_S * fs))
    seg = uc[search_lo:search_hi]
    if len(seg) == 0:
        return None

    pks, _ = find_peaks(seg, prominence=UC_PEAK_PROMINENCE)
    if len(pks) == 0:
        return None

    # Choose peak closest to the event's nadir region (center of event)
    event_center = (event_start + event_end) // 2
    abs_pks = [search_lo + p for p in pks]
    return min(abs_pks, key=lambda p: abs(p - event_center))


def detect_decelerations(
    fhr: np.ndarray,
    uc: np.ndarray,
    fs: float = 4.0,
) -> DecelerationSummary:
    """Detect and classify FHR decelerations.

    Args:
        fhr: FHR signal in bpm, shape (T,).
        uc:  UC signal in mmHg, shape (T,).
        fs:  Sampling frequency in Hz (default 4.0).

    Returns:
        DecelerationSummary with counts and max depth.
    """
    try:
        fhr = np.asarray(fhr, dtype=float)
        uc  = np.asarray(uc,  dtype=float)
        if len(fhr) == 0:
            return DecelerationSummary()

        fhr = _ffill(fhr)
        uc  = _ffill(uc)

        baseline = _compute_rolling_baseline(fhr, fs, ROLLING_WINDOW_S)
        events   = _find_dip_events(fhr, baseline, fs)

        n_late    = 0
        n_var     = 0
        n_prolong = 0
        max_depth = 0.0

        for start, end in events:
            duration_s = (end - start) / fs
            seg        = fhr[start:end]
            nadir_rel  = int(np.argmin(seg))
            nadir_idx  = start + nadir_rel
            nadir_val  = float(seg[nadir_rel])

            # Depth relative to baseline at nadir
            depth = float(baseline[nadir_idx] - nadir_val)
            if depth > max_depth:
                max_depth = depth

            # ── Prolonged (≥2 min): classify first, don't double-count ────────
            if duration_s >= PROLONGED_MIN_S:
                n_prolong += 1
                continue

            # ── True onset-to-nadir → abrupt vs gradual ───────────────────────
            onset_idx = _true_onset_idx(fhr, baseline, start, fs)
            descent_s = (nadir_idx - onset_idx) / fs

            if descent_s < VARIABLE_ONSET_S:
                # Abrupt onset → Variable deceleration
                n_var += 1
            else:
                # Gradual onset → Late or Early (benign)
                # Requires a visible UC peak to determine timing
                uc_peak_idx = _find_nearest_uc_peak(uc, start, end, fs)

                if uc_peak_idx is None:
                    # No identifiable contraction: cannot classify as late/early.
                    # Conservatively count as variable rather than assume late.
                    n_var += 1
                    continue

                # Nadir lag relative to UC peak:
                #   positive → nadir AFTER peak → potentially late
                #   negative → nadir BEFORE peak → early (benign, not counted)
                nadir_lag_s = (nadir_idx - uc_peak_idx) / fs
                if nadir_lag_s > LATE_NADIR_LAG_S:
                    n_late += 1
                # Early decelerations (benign): intentionally not counted

        return DecelerationSummary(
            n_late_decelerations       = float(n_late),
            n_variable_decelerations   = float(n_var),
            n_prolonged_decelerations  = float(n_prolong),
            max_deceleration_depth_bpm = max_depth,
        )

    except Exception as exc:
        log.warning(f"[decelerations] Failed: {exc}. Returning safe defaults.")
        return DecelerationSummary()


def _ffill(arr: np.ndarray) -> np.ndarray:
    """Forward-fill NaN values, then backward-fill any remaining."""
    out = arr.copy()
    mask = np.isnan(out)
    if not mask.any():
        return out
    idx = np.where(~mask, np.arange(len(out)), 0)
    np.maximum.accumulate(idx, out=idx)
    out[mask] = out[idx[mask]]
    # backward-fill any leading NaNs
    mask2 = np.isnan(out)
    if mask2.any():
        idx2 = np.where(~mask2, np.arange(len(out)), len(out) - 1)
        np.minimum.accumulate(idx2[::-1], out=idx2[::-1])
        out[mask2] = out[idx2[mask2]]
    return out

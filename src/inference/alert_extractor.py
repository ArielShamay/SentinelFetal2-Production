"""
alert_extractor.py — Alert Segment Extraction + Feature Computation
====================================================================
Source: arXiv:2601.06149v1, Section II-F, Figure 5
SSOT:   docs/plan_2.md §4.1

plan_2 §4.1 — 12 features (was 4/6)
--------------------------------------
Features 1-6:  unchanged from S14 (segment_length, max_prediction,
               cumulative_sum, weighted_integral, n_alert_segments,
               alert_fraction)
Features 7-12: NEW — mean_prediction, std_prediction,
               max_pred_all_segments, total_alert_duration,
               recording_max_score, recording_mean_above_th

Alert threshold = 0.4 (Deviation S11, validated 2026-02-23)
Inference stride = 24 (plan_2 §4.4 — MUST be identical for train+test)
Feature count   = 12 (plan_2, was 4/6)

Usage::

    from src.inference.alert_extractor import (
        extract_alert_segments, compute_alert_features,
        extract_recording_features,
        ALERT_THRESHOLD
    )

    segments = extract_alert_segments(scores, threshold=ALERT_THRESHOLD)
    feats = extract_recording_features(scores, threshold=ALERT_THRESHOLD,
                                        inference_stride=24, fs=4.0)
"""

from __future__ import annotations

from typing import Dict, List, Tuple

import numpy as np


# ---------------------------------------------------------------------------
# Thresholds  (Deviation S11 — validated 2026-02-23)
# ---------------------------------------------------------------------------

ALERT_THRESHOLD: float = 0.4     # S11: lowered from paper 0.5; eliminates zero-segment FNs
DECISION_THRESHOLD: float = 0.284  # Youden-optimal LR decision threshold (test AUC 0.839)


# ---------------------------------------------------------------------------
# extract_alert_segments
# ---------------------------------------------------------------------------

def extract_alert_segments(
    scores: List[Tuple[int, float]],
    threshold: float = ALERT_THRESHOLD,
) -> List[Tuple[int, int, List[float]]]:
    """Identify contiguous windows where score > threshold.

    Source: arXiv:2601.06149v1, Section II-F — "alert segment = contiguous
    sequence of windows with NN score > 0.5".

    Args:
        scores:    List of (start_sample, score) tuples from inference_recording().
        threshold: Score cutoff for alert classification (default 0.5).

    Returns:
        List of (start_sample, end_sample, segment_scores) where:
            start_sample:   int         — first sample of the alert segment.
            end_sample:     int         — first sample of the window AFTER the
                                          last alert window (exclusive endpoint).
            segment_scores: List[float] — per-window P(acidemia) values.

        Empty list if no windows exceed threshold.
    """
    if len(scores) == 0:
        return []

    alert_mask = [s > threshold for _, s in scores]

    segments: List[Tuple[int, int, List[float]]] = []
    in_segment = False
    seg_start_sample: int = 0
    seg_scores: List[float] = []

    for i, (start_sample, score) in enumerate(scores):
        if alert_mask[i]:
            if not in_segment:
                # Begin new segment
                in_segment = True
                seg_start_sample = start_sample
                seg_scores = []
            seg_scores.append(score)
        else:
            if in_segment:
                # Close the segment: end_sample = start of *this* (non-alert) window
                segments.append((seg_start_sample, start_sample, list(seg_scores)))
                in_segment = False
                seg_scores = []

    # Handle segment running to the end of the recording
    if in_segment and seg_scores:
        # Estimate end: last start_sample + 1800 (window length)
        last_start, _ = scores[-1]
        end_sample = last_start + 1800
        segments.append((seg_start_sample, end_sample, list(seg_scores)))

    return segments


# ---------------------------------------------------------------------------
# compute_alert_features — per-segment (features 1-4, backward compat)
# ---------------------------------------------------------------------------

def compute_alert_features(
    segment_scores: List[float],
    inference_stride: int = 1,
    fs: float = 4.0,
) -> Dict[str, float]:
    """Compute 4 alert features from a single contiguous alert segment.

    Source: arXiv:2601.06149v1, Section II-F.
    P5 fix v2: all time-based features normalized by dt = stride/fs.
    Features 5-12 require all segments — see extract_recording_features().

    Args:
        segment_scores:   Per-window P(acidemia) scores within the segment.
        inference_stride: Stride used in inference (samples). Must match LR training.
        fs:               Sampling frequency in Hz (4 Hz).

    Returns:
        dict with 4 keys: segment_length, max_prediction,
                          cumulative_sum, weighted_integral.
    """
    if len(segment_scores) == 0:
        raise ValueError("segment_scores must be non-empty.")

    p = np.asarray(segment_scores, dtype=np.float64)
    dt = inference_stride / fs

    return {
        "segment_length":    float(len(p) * dt / 60.0),
        "max_prediction":    float(np.max(p)),
        "cumulative_sum":    float(np.sum(p) * dt),
        "weighted_integral": float(np.sum((p - 0.5) ** 2) * dt),
    }


# ---------------------------------------------------------------------------
# extract_recording_features — all 12 features (plan_2 §4.1)
# ---------------------------------------------------------------------------

def extract_recording_features(
    scores: List[Tuple[int, float]],
    threshold: float = ALERT_THRESHOLD,
    inference_stride: int = 24,
    fs: float = 4.0,
    n_features: int = 12,
) -> Dict[str, float]:
    """Compute all recording-level features for the LR classifier.

    plan_2 §4.1: expanded from 6 to 12 features.
    Features are computed from the longest alert segment (features 1-4, 7-8)
    and from the full recording (features 5-6, 9-12).

    Args:
        scores:           List of (start_sample, score) from inference_recording().
        threshold:        Alert segment threshold (default 0.40).
        inference_stride: Stride used in inference — MUST match LR training stride.
        fs:               Sampling frequency (4 Hz).
        n_features:       6 (legacy) or 12 (plan_2 default).

    Returns:
        Dict with n_features keys (all float).
        If no alert segments: all features are 0.0.
    """
    segments = extract_alert_segments(scores, threshold=threshold)
    all_scores = [s for _, s in scores]
    dt = inference_stride / fs

    # ---- Zero baseline (no alert activity) -----------------------------------
    if not segments:
        zero: Dict[str, float] = {
            "segment_length":        0.0,
            "max_prediction":        0.0,
            "cumulative_sum":        0.0,
            "weighted_integral":     0.0,
            "n_alert_segments":      0.0,
            "alert_fraction":        0.0,
        }
        if n_features == 12:
            zero.update({
                "mean_prediction":       0.0,
                "std_prediction":        0.0,
                "max_pred_all_segments": 0.0,
                "total_alert_duration":  0.0,
                "recording_max_score":   float(np.max(all_scores)) if all_scores else 0.0,
                "recording_mean_above_th": 0.0,
            })
        return zero

    # ---- Longest segment (features 1-4) ----------------------------------------
    longest_seg_scores = max(segments, key=lambda s: len(s[2]))[2]
    p_long = np.asarray(longest_seg_scores, dtype=np.float64)

    feats: Dict[str, float] = {
        "segment_length":    float(len(p_long) * dt / 60.0),
        "max_prediction":    float(np.max(p_long)),
        "cumulative_sum":    float(np.sum(p_long) * dt),
        "weighted_integral": float(np.sum((p_long - 0.5) ** 2) * dt),
    }

    # ---- Recording-level (features 5-6) ----------------------------------------
    n_alert_windows = sum(len(seg[2]) for seg in segments)
    n_total_windows = len(scores)
    feats["n_alert_segments"] = float(len(segments))
    feats["alert_fraction"]   = float(n_alert_windows / max(n_total_windows, 1))

    if n_features == 12:
        # Features 7-8: stats of longest segment
        feats["mean_prediction"] = float(np.mean(p_long))
        feats["std_prediction"]  = float(np.std(p_long)) if len(p_long) > 1 else 0.0

        # Feature 9: max prediction across ALL segments
        all_seg_scores = [s for _, _, seg in segments for s in seg]
        feats["max_pred_all_segments"] = float(np.max(all_seg_scores))

        # Feature 10: total alert duration in minutes
        feats["total_alert_duration"] = float(n_alert_windows * dt / 60.0)

        # Feature 11: recording-level max score (no threshold applied)
        feats["recording_max_score"] = float(np.max(all_scores))

        # Feature 12: mean score over all windows that exceed threshold
        above_th = [s for _, s in scores if s > threshold]
        feats["recording_mean_above_th"] = float(np.mean(above_th)) if above_th else 0.0

    assert len(feats) == n_features, (
        f"BUG: expected {n_features} features, got {len(feats)}: {list(feats.keys())}"
    )
    return feats


# ---------------------------------------------------------------------------
# Convenience: zero feature vector (backward compat)
# ---------------------------------------------------------------------------

ZERO_FEATURES: Dict[str, float] = {
    # Features 1-6 (original 4 + S14 additions)
    "segment_length":        0.0,
    "max_prediction":        0.0,
    "cumulative_sum":        0.0,
    "weighted_integral":     0.0,
    "n_alert_segments":      0.0,
    "alert_fraction":        0.0,
    # Features 7-12 (plan_2 §4.1 additions)
    "mean_prediction":       0.0,
    "std_prediction":        0.0,
    "max_pred_all_segments": 0.0,
    "total_alert_duration":  0.0,
    "recording_max_score":   0.0,
    "recording_mean_above_th": 0.0,
}
"""Zero feature vector for recordings with NO alert segments (plan_2 §4.1, 12 features).

Use extract_recording_features(scores, n_features=12) for normal usage.
This constant is provided for initialisation / fallback only.
"""

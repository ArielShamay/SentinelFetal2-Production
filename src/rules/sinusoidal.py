"""
src/rules/sinusoidal.py — Sinusoidal FHR Pattern Detector
==========================================================
Ported from github.com/ArielShamay/SentinelFetal (stripped of API/framework deps).

Algorithm (Israeli Position Paper):
- Sinusoidal: smooth, wave-like oscillations at 3–5 cycles/min (0.05–0.083 Hz)
- Amplitude: 5–15 bpm, sustained for ≥20 minutes
- Detection via FFT: dominant frequency in target band, dominance ratio > threshold

Clinical significance: PATHOLOGICAL — indicates severe fetal anemia or hypoxia.

Input:  fhr (T,) — raw FHR in bpm, 4 Hz
Output: SinusoidalResult dataclass
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np

log = logging.getLogger(__name__)

# Band boundaries (cycles per second at 4 Hz)
FREQ_LOW_HZ  = 0.05   # 3 cycles/min
FREQ_HIGH_HZ = 0.083  # 5 cycles/min

# Detection thresholds
MIN_AMPLITUDE_BPM   = 3.0    # bpm  (peak amplitude of band-pass component)
MAX_AMPLITUDE_BPM   = 25.0   # bpm  (was 15 — relaxed; original spec uses 5–15 but real
                             #        sinusoidal often slightly exceeds this)
MIN_DOMINANCE_RATIO = 0.10   # fraction of total spectral power in target band
                             # (was 0.15 — relaxed slightly for noisy CTG signals)
MIN_DURATION_MIN    = 20.0   # minutes of sustained pattern required

# Minimum signal length for FFT analysis
MIN_SAMPLES_FOR_FFT_MIN = 5.0  # minutes


@dataclass
class SinusoidalResult:
    sinusoidal_detected: float = 0.0  # 0.0 or 1.0
    dominant_freq_hz:    float = 0.0
    amplitude_bpm:       float = 0.0
    dominance_ratio:     float = 0.0


def _check_segment(
    segment: np.ndarray,
    fs: float,
) -> tuple[bool, float, float, float]:
    """Check if a signal segment has sinusoidal characteristics.

    Returns: (is_sinusoidal, dominant_freq, amplitude, dominance)
    """
    n = len(segment)
    freqs = np.fft.rfftfreq(n, d=1.0 / fs)
    power = np.abs(np.fft.rfft(segment - np.mean(segment))) ** 2

    # Power in target band
    in_band = (freqs >= FREQ_LOW_HZ) & (freqs <= FREQ_HIGH_HZ)
    total_power = float(np.sum(power))
    band_power  = float(np.sum(power[in_band]))

    if total_power < 1e-9:
        return False, 0.0, 0.0, 0.0

    dominance = band_power / total_power

    if not np.any(in_band):
        return False, 0.0, 0.0, dominance

    peak_in_band_idx = int(np.argmax(power[in_band]))
    dominant_freq    = float(freqs[in_band][peak_in_band_idx])

    # Amplitude: peak amplitude of the sinusoidal component, estimated from
    # the in-band power only.
    #
    # For a pure sinusoid x[t] = A*sin(2πft) of length n, the np.fft.rfft
    # coefficient magnitude at frequency f is |X[k]| ≈ n*A/2.
    # Therefore:  band_power ≈ (n*A/2)²
    #             A = 2 * sqrt(band_power) / n
    #
    # Using band_power (not total power) isolates the sinusoidal component
    # from background variability and noise, avoiding the std*2 over-estimate.
    if np.any(in_band) and n > 0:
        amplitude = float(2.0 * np.sqrt(band_power) / n)
    else:
        amplitude = 0.0

    is_sinusoidal = (
        dominance >= MIN_DOMINANCE_RATIO
        and MIN_AMPLITUDE_BPM <= amplitude <= MAX_AMPLITUDE_BPM
    )

    return is_sinusoidal, dominant_freq, amplitude, dominance


def detect_sinusoidal_pattern(
    fhr: np.ndarray,
    fs: float = 4.0,
) -> SinusoidalResult:
    """Detect sinusoidal FHR pattern.

    Uses FFT analysis on the full signal and also on sliding 20-minute windows
    to check for sustained sinusoidal activity.

    Args:
        fhr: FHR signal in bpm, shape (T,).
        fs:  Sampling frequency in Hz (default 4.0).

    Returns:
        SinusoidalResult with sinusoidal_detected (0/1), frequency, amplitude, dominance.
    """
    try:
        fhr = np.asarray(fhr, dtype=float)
        valid = fhr[~np.isnan(fhr)]

        if len(valid) < int(MIN_SAMPLES_FOR_FFT_MIN * 60 * fs):
            return SinusoidalResult()

        # Use the full signal for global FFT
        is_sin, freq, amp, dom = _check_segment(valid, fs)

        if not is_sin:
            return SinusoidalResult(
                dominant_freq_hz = freq,
                amplitude_bpm    = amp,
                dominance_ratio  = dom,
            )

        # Check duration: need ≥20 continuous minutes of sinusoidal activity
        # Sliding window (20 min) majority vote
        win_samples = int(MIN_DURATION_MIN * 60 * fs)
        stride      = int(60 * fs)  # 1-minute stride

        if len(valid) < win_samples:
            # Signal shorter than 20 min — accept global result if detected
            return SinusoidalResult(
                sinusoidal_detected = 1.0,
                dominant_freq_hz    = freq,
                amplitude_bpm       = amp,
                dominance_ratio     = dom,
            )

        sustained_count = 0
        total_windows   = 0

        for start in range(0, len(valid) - win_samples + 1, stride):
            seg = valid[start : start + win_samples]
            total_windows += 1
            w_sin, _, _, _ = _check_segment(seg, fs)
            if w_sin:
                sustained_count += 1

        # Consider detected if ≥50% of windows are sinusoidal
        sustained = total_windows > 0 and (sustained_count / total_windows) >= 0.5

        return SinusoidalResult(
            sinusoidal_detected = 1.0 if sustained else 0.0,
            dominant_freq_hz    = freq,
            amplitude_bpm       = amp,
            dominance_ratio     = dom,
        )

    except Exception as exc:
        log.warning(f"[sinusoidal] Failed: {exc}. Returning safe defaults.")
        return SinusoidalResult()

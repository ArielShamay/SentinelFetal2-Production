"""
sliding_window.py — Sliding Window Inference for SentinelFatal2
================================================================
Source: arXiv:2601.06149v1, Section II-F, Figure 5
SSOT:   docs/work_plan.md, Part ו, שלב 5.1

Two inference strides (P4 fix):
    INFERENCE_STRIDE_REPRO   = 1   -- official evaluation (Stage 7)
    INFERENCE_STRIDE_RUNTIME = 60  -- operational demo only (15-second steps)

CRITICAL: LR training (train_lr.py) and evaluation (Stage 7) MUST use
the same stride.  Official evaluation always uses INFERENCE_STRIDE_REPRO.

Usage::

    from src.inference.sliding_window import inference_recording, INFERENCE_STRIDE_REPRO

    scores = inference_recording(model, signal, stride=INFERENCE_STRIDE_REPRO)
    # scores: list of (start_sample: int, score: float)
"""

from __future__ import annotations

from typing import List, Tuple, Union

import numpy as np
import torch


# ---------------------------------------------------------------------------
# Stride constants (LOCKED)
# ---------------------------------------------------------------------------

INFERENCE_STRIDE_REPRO: int = 1    # repro_mode: exact paper comparison (Stage 7)
INFERENCE_STRIDE_RUNTIME: int = 60  # runtime_mode: fast operational demo ONLY

# Window length (samples) — fixed at 1800 (7.5 min @ 4 Hz)
_WINDOW_LEN: int = 1800


# ---------------------------------------------------------------------------
# inference_recording
# ---------------------------------------------------------------------------

def inference_recording(
    model: torch.nn.Module,
    signal: Union[np.ndarray, torch.Tensor],
    stride: int = INFERENCE_STRIDE_REPRO,
    device: str = "cpu",
    batch_size: int = 256,
) -> List[Tuple[int, float]]:
    """Run sliding-window inference on a single full-length recording.

    Source: arXiv:2601.06149v1, Section II-F — "sliding window" evaluation.

    Args:
        model:      PatchTST with ClassificationHead (eval mode recommended).
        signal:     (2, T) array/tensor — FHR (ch0) and UC (ch1); T >= 1800.
        stride:     Sliding stride in samples.
                    Use INFERENCE_STRIDE_REPRO (1)   for official evaluation.
                    Use INFERENCE_STRIDE_RUNTIME (60) for demo/visualization only.
        device:     Torch device string ('cpu' or 'cuda').
        batch_size: Number of windows per forward pass (default 256).

    Returns:
        List of (start_sample, score) tuples where:
            start_sample: int  — index of the first sample in the window.
            score:        float — P(acidemia) in [0, 1].

    Raises:
        ValueError: If signal has fewer than WINDOW_LEN samples.
    """
    # ------------------------------------------------------------------
    # Normalize input to tensor (2, T)
    # ------------------------------------------------------------------
    if isinstance(signal, np.ndarray):
        signal_t = torch.from_numpy(signal.copy()).float()
    else:
        signal_t = signal.float()

    if signal_t.ndim != 2 or signal_t.shape[0] != 2:
        raise ValueError(
            f"Expected signal shape (2, T), got {tuple(signal_t.shape)}"
        )

    T = signal_t.shape[1]
    if T < _WINDOW_LEN:
        raise ValueError(
            f"Signal length {T} is shorter than window length {_WINDOW_LEN}."
        )

    signal_t = signal_t.to(device)

    # ------------------------------------------------------------------
    # Collect all window start positions
    # ------------------------------------------------------------------
    starts = list(range(0, T - _WINDOW_LEN + 1, stride))

    # ------------------------------------------------------------------
    # Batched sliding window inference
    # ------------------------------------------------------------------
    model.eval()
    model.to(device)

    scores: List[Tuple[int, float]] = []

    with torch.no_grad():
        for i in range(0, len(starts), batch_size):
            batch_starts = starts[i : i + batch_size]
            windows = torch.stack([
                signal_t[:, s : s + _WINDOW_LEN] for s in batch_starts
            ])  # (B, 2, 1800)

            logits = model(windows)                                  # (B, 2)
            probs = logits.softmax(dim=-1)[:, 1].tolist()           # list[float]

            for s, p in zip(batch_starts, probs):
                scores.append((s, p))

    return scores

"""
utils.py — Fine-tuning Utilities
==================================
Source: arXiv:2601.06149v1, Section II-E
SSOT:   docs/work_plan.md, Part ו, שלב 4

Functions:
    compute_recording_auc() — P7 fix: AUC per-recording with max aggregation
    sliding_windows()       — Extract overlapping windows from signal
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Tuple, Union

import numpy as np
import pandas as pd
import torch
from sklearn.metrics import roc_auc_score


def sliding_windows(
    signal: np.ndarray,
    window_len: int = 1800,
    stride: int = 1,
) -> List[torch.Tensor]:
    """Extract overlapping windows from a signal.

    Args:
        signal: (2, T) numpy array — FHR and UC channels.
        window_len: Window size in samples (1800).
        stride: Sliding stride in samples (1 for dense evaluation).

    Returns:
        List of (2, window_len) torch tensors.
    """
    T = signal.shape[1]
    windows = []
    for start in range(0, T - window_len + 1, stride):
        window = signal[:, start : start + window_len]
        windows.append(torch.from_numpy(window.copy()))
    return windows


def compute_recording_auc(
    model: torch.nn.Module,
    split_csv: Union[str, Path],
    processed_dir: Union[str, Path],
    stride: int = 1,
    device: str = "cpu",
    eval_batch_size: int = 256,
) -> float:
    """Compute AUC per-recording (P7 fix) with batched inference.

    Training unit = window. Evaluation unit = RECORDING.
    Aggregation function (LOCKED): max(window_scores) per recording.

    Args:
        model: PatchTST with ClassificationHead.
        split_csv: Path to train.csv or val.csv (cols: id, target, fname).
        processed_dir: Path to data/processed/ directory.
        stride: Inference stride (900 for training validation, 1 for Stage 7 eval).
        device: 'cpu' or 'cuda'.
        eval_batch_size: Number of windows per forward pass (default 256).

    Returns:
        ROC-AUC score across all recordings.

    Raises:
        ValueError: If split_csv has no recordings or all predictions constant.
    """
    model.eval()
    model.to(device)

    df = pd.read_csv(split_csv, dtype={"id": str, "target": int})
    if len(df) == 0:
        raise ValueError(f"Empty CSV: {split_csv}")

    processed_dir = Path(processed_dir)
    y_true: List[int] = []
    y_pred: List[float] = []

    with torch.no_grad():
        for _, row in df.iterrows():
            recording_id = str(row["id"])
            label = int(row["target"])
            npy_path = processed_dir / "ctu_uhb" / f"{recording_id}.npy"

            if not npy_path.exists():
                print(f"[compute_recording_auc] WARNING: {npy_path} not found, skipping")
                continue

            # Load full recording
            signal = np.load(npy_path, mmap_mode="r")  # (2, T)
            windows = sliding_windows(signal, window_len=1800, stride=stride)

            if len(windows) == 0:
                print(f"[compute_recording_auc] WARNING: no windows for {recording_id}, skipping")
                continue

            # Batched inference — process windows in chunks for GPU efficiency
            scores: List[float] = []
            for i in range(0, len(windows), eval_batch_size):
                batch = torch.stack(windows[i : i + eval_batch_size]).to(device)
                logits = model(batch)
                probs = torch.softmax(logits, dim=-1)[:, 1].tolist()
                scores.extend(probs)

            # P7 fix: aggregation = max
            recording_score = max(scores)
            y_true.append(label)
            y_pred.append(recording_score)

    if len(y_true) == 0:
        raise ValueError(f"No valid recordings loaded from {split_csv}")

    # Check if all predictions are constant (would cause AUC error)
    if len(set(y_pred)) == 1:
        print(f"[compute_recording_auc] WARNING: All predictions constant ({y_pred[0]:.4f}), AUC undefined")
        return 0.5  # Return random baseline

    return roc_auc_score(y_true, y_pred)

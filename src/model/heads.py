"""
heads.py — Prediction Heads for PatchTST
==========================================
Two heads matching the paper's two training phases:

PretrainingHead
    Reconstruction of masked FHR patches (MAE objective).
    Source: arXiv:2601.06149v1, Section II-D, Equation 2, Figure 4.

ClassificationHead
    Binary acidemia prediction (fine-tuning objective).
    Source: arXiv:2601.06149v1, Section II-E.
    "A linear layer mapping the flattened encoder output to two classes."
"""

from __future__ import annotations

from typing import List

import torch
import torch.nn as nn


# ---------------------------------------------------------------------------
# Pre-training Head (MAE reconstruction)
# ---------------------------------------------------------------------------

class PretrainingHead(nn.Module):
    """Reconstruct masked FHR patches from encoder representations.

    Loss (Equation 2):
        L = (1/|M|) · Σ_{i∈M} ||x^FHR_i − x̂^FHR_i||²

    Usage::

        head = PretrainingHead(d_model=128, patch_len=48)
        model.replace_head(head)
        pred = model(x, mask_indices=mask_idx)   # (B, n_masked, 48)
        loss = F.mse_loss(pred, target_patches)

    Args:
        d_model:   encoder embedding dimension (128 — assumption S2).
        patch_len: raw samples per patch (48 per paper).
    """

    def __init__(self, d_model: int = 128, patch_len: int = 48) -> None:
        super().__init__()
        # Linear projection from embedding space back to patch space
        self.proj = nn.Linear(d_model, patch_len)

    def forward(
        self,
        enc_output: torch.Tensor,
        mask_indices: List[int],
    ) -> torch.Tensor:
        """
        Args:
            enc_output:   (batch, n_patches, d_model)  — FHR encoder output.
            mask_indices: list of int patch positions that were masked.

        Returns:
            (batch, n_masked, patch_len)  — reconstructed values for masked patches.
        """
        # Select only the masked patch representations
        masked_enc = enc_output[:, mask_indices, :]    # (B, n_masked, d_model)
        return self.proj(masked_enc)                   # (B, n_masked, patch_len)


# ---------------------------------------------------------------------------
# Classification Head (fine-tuning)
# ---------------------------------------------------------------------------

class ClassificationHead(nn.Module):
    """Binary acidemia classification head.

    Paper Section II-E:
        "A linear layer mapping the flattened encoder output to two classes."
        → single nn.Linear, no hidden layer.

    Dropout (0.2) is applied before the linear layer, consistent with
    paper Section II-D which states dropout=0.2 is used throughout the model.

    Output: raw logits (batch, 2) — softmax / CrossEntropyLoss applied outside
    the model in the training loop (confirmed by user).

    Args:
        d_in:      input dimension = n_patches * d_model * n_channels
                   = 73 * 128 * 2 = 18688  (⚠ assumption S2: d_model=128).
        n_classes: number of output classes (2 for binary acidemia).
        dropout:   dropout probability (0.2 per paper).
    """

    def __init__(
        self,
        d_in: int = 18688,
        n_classes: int = 2,
        dropout: float = 0.2,
    ) -> None:
        super().__init__()
        self.dropout = nn.Dropout(dropout)
        self.linear = nn.Linear(d_in, n_classes)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """
        Args:
            x: (batch, d_in)  — concatenated & flattened FHR+UC repr.

        Returns:
            (batch, n_classes)  — raw logits.
        """
        return self.linear(self.dropout(x))

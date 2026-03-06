"""
patchtst.py — PatchTST Channel-Independent Architecture
=========================================================
Source: arXiv:2601.06149v1, Section II-C, Equation 1, Figure 3
SSOT:   docs/work_plan.md, Part ה (Hyperparameters Reference Card)

Architecture overview
---------------------
• Input : (batch, 2, 1800)  — 2 channels (FHR, UC), 1800 samples @ 4 Hz
• Patching: patch_len=48, stride=24 → n_patches=73 per channel (✓ paper)
• Embedding: Linear(48, 128) + learnable positional embedding (✓ Equation 1)
• Encoder:  3-layer Transformer with BatchNorm (pre-norm), 4 heads,
            FFN dim=256, dropout=0.2 (✓ paper Section II-C)
• Channel-independent: FHR and UC pass through the **same** encoder
  (shared weights); processed separately then combined for classification.
• Two pluggable heads:
    – PretrainingHead   → reconstruct masked FHR patches
    – ClassificationHead → 2-class acidemia prediction
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import List, Optional, Union

import torch
import torch.nn as nn
import yaml


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_config(path: Union[str, Path], overrides: dict = None) -> dict:
    """Load YAML config and return as nested dict.

    Args:
        path:      Path to YAML config file.
        overrides: Optional flat dict of overrides.  Keys that exist in
                   cfg['model'] (e.g. d_model, n_layers, dropout) are written
                   there; all other keys go to cfg['finetune'].
    """
    with open(path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    if overrides:
        model_keys = set(cfg.get("model", {}).keys())
        for k, v in overrides.items():
            if k in model_keys:
                cfg["model"][k] = v
            else:
                cfg.setdefault("finetune", {})[k] = v
    return cfg


# ---------------------------------------------------------------------------
# Patch Embedding  (Equation 1: x_d = W_P · x_p + W_pos)
# ---------------------------------------------------------------------------

class PatchEmbedding(nn.Module):
    """Linear projection of raw patches plus learnable positional embedding.

    Args:
        patch_len: number of time-steps per patch (48 per paper).
        d_model:   embedding dimension (128 — assumption S2).
        n_patches: total number of patches per window (73 per paper).
        dropout:   dropout applied after embedding (0.2 per paper).
    """

    def __init__(
        self,
        patch_len: int = 48,
        d_model: int = 128,
        n_patches: int = 73,
        dropout: float = 0.2,
    ) -> None:
        super().__init__()
        # W_P in Equation 1
        self.projection = nn.Linear(patch_len, d_model)
        # W_pos in Equation 1 — learnable, one vector per patch position
        self.pos_embedding = nn.Parameter(torch.zeros(1, n_patches, d_model))
        self.dropout = nn.Dropout(dropout)
        nn.init.trunc_normal_(self.pos_embedding, std=0.02)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """
        Args:
            x: (batch, n_patches, patch_len)
        Returns:
            (batch, n_patches, d_model)
        """
        return self.dropout(self.projection(x) + self.pos_embedding)


# ---------------------------------------------------------------------------
# Single Transformer Encoder Layer  (BatchNorm, pre-norm variant)
# ---------------------------------------------------------------------------

class _TransformerEncoderLayer(nn.Module):
    """One Transformer layer using BatchNorm in the pre-norm configuration.

    Order per sub-layer (user-confirmed pre-norm):
        BN(x) → MHSA → dropout → + x  (residual)
        BN(x) → FFN  → dropout → + x  (residual)

    BatchNorm applied as BN1d over the feature dimension:
        (B, S, D) → transpose(1,2) → (B, D, S) → BN1d(D) → transpose back.

    Source: work_plan.md Section ה.3; ✓ BatchNorm per paper Section II-C.

    Args:
        d_model:  embedding dimension.
        n_heads:  number of attention heads.
        ffn_dim:  feed-forward hidden dimension (256 — assumption S2).
        dropout:  dropout probability (0.2 per paper).
    """

    def __init__(
        self,
        d_model: int = 128,
        n_heads: int = 4,
        ffn_dim: int = 256,
        dropout: float = 0.2,
    ) -> None:
        super().__init__()
        # Pre-norm 1 (before MHSA)
        self.norm1 = nn.BatchNorm1d(d_model)
        self.attn = nn.MultiheadAttention(
            embed_dim=d_model,
            num_heads=n_heads,
            dropout=dropout,
            batch_first=True,
        )
        # Pre-norm 2 (before FFN)
        self.norm2 = nn.BatchNorm1d(d_model)
        self.ffn = nn.Sequential(
            nn.Linear(d_model, ffn_dim),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(ffn_dim, d_model),
        )
        self.dropout = nn.Dropout(dropout)

    def _bn(self, x: torch.Tensor, bn: nn.BatchNorm1d) -> torch.Tensor:
        """Apply BatchNorm1d to (B, S, D) by transposing to (B, D, S)."""
        return bn(x.transpose(1, 2)).transpose(1, 2)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """
        Args:
            x: (batch, n_patches, d_model)
        Returns:
            (batch, n_patches, d_model)
        """
        # — MHSA branch —
        normed = self._bn(x, self.norm1)                          # pre-norm
        attn_out, _ = self.attn(normed, normed, normed)
        x = x + self.dropout(attn_out)                            # residual

        # — FFN branch —
        normed = self._bn(x, self.norm2)                          # pre-norm
        x = x + self.dropout(self.ffn(normed))                    # residual
        return x


# ---------------------------------------------------------------------------
# Stacked Transformer Encoder
# ---------------------------------------------------------------------------

class TransformerEncoder(nn.Module):
    """Stack of num_layers identical TransformerEncoderLayers (shared config).

    Args:
        d_model, n_heads, ffn_dim, dropout, num_layers: see _TransformerEncoderLayer.
    """

    def __init__(
        self,
        d_model: int = 128,
        n_heads: int = 4,
        ffn_dim: int = 256,
        dropout: float = 0.2,
        num_layers: int = 3,
    ) -> None:
        super().__init__()
        self.layers = nn.ModuleList(
            [
                _TransformerEncoderLayer(d_model, n_heads, ffn_dim, dropout)
                for _ in range(num_layers)
            ]
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """
        Args:
            x: (batch, n_patches, d_model)
        Returns:
            (batch, n_patches, d_model)
        """
        for layer in self.layers:
            x = layer(x)
        return x


# ---------------------------------------------------------------------------
# PatchTST — main model
# ---------------------------------------------------------------------------

class PatchTST(nn.Module):
    """Channel-Independent PatchTST with pluggable head.

    Channel independence (✓ paper Section II-C):
        FHR and UC channels each pass through the **same** encoder
        (``patch_embed`` and ``encoder`` are shared, not duplicated).

    Head is set via :meth:`replace_head` after construction:
        • :class:`~src.model.heads.PretrainingHead`    — MAE reconstruction
        • :class:`~src.model.heads.ClassificationHead` — acidemia prediction

    Args:
        config: dict (from ``load_config``) or path to train_config.yaml.
    """

    def __init__(self, config: Union[dict, str, Path]) -> None:
        super().__init__()

        if not isinstance(config, dict):
            config = load_config(config)

        data_cfg  = config["data"]
        model_cfg = config["model"]

        self.patch_len    = int(data_cfg["patch_len"])     # 48
        self.patch_stride = int(data_cfg["patch_stride"])  # 24
        self.n_patches    = int(data_cfg["n_patches"])     # 73
        self.d_model      = int(model_cfg["d_model"])      # 128

        # Shared embedding + encoder (channel-independent = same weights)
        self.patch_embed = PatchEmbedding(
            patch_len=self.patch_len,
            d_model=self.d_model,
            n_patches=self.n_patches,
            dropout=float(model_cfg["dropout"]),
        )
        self.encoder = TransformerEncoder(
            d_model=self.d_model,
            n_heads=int(model_cfg["n_heads"]),
            ffn_dim=int(model_cfg["ffn_dim"]),
            dropout=float(model_cfg["dropout"]),
            num_layers=int(model_cfg["num_layers"]),
        )

        # Head is None until replace_head() is called
        self.head: Optional[nn.Module] = None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _extract_patches(self, x: torch.Tensor) -> torch.Tensor:
        """Unfold a 1-D channel signal into overlapping patches.

        Crops the signal to exactly ``n_patches`` patches before unfolding.
        Required length = (n_patches - 1) * patch_stride + patch_len = 1776.
        The last 24 samples of the 1800-sample window are unused (≈ 6 seconds).

        Note (deviation S9): the SSOT formula "(1800-48)/24+1 = 73" contains
        an arithmetic error; the correct PyTorch unfold on a 1800-sample input
        gives 74 patches.  We enforce 73 by cropping to 1776 samples to match
        the paper's stated n_patches=73.  Logged in docs/deviation_log.md as S9.

        Args:
            x: (batch, seq_len)  e.g. (B, 1800)
        Returns:
            (batch, n_patches, patch_len)  e.g. (B, 73, 48)
        """
        # Crop to ensure exactly n_patches patches
        end = (self.n_patches - 1) * self.patch_stride + self.patch_len  # 1776
        patches = x[..., :end].unfold(-1, self.patch_len, self.patch_stride)
        # shape: (B, n_patches, patch_len)
        return patches.contiguous()

    def encode_channel(self, x_channel: torch.Tensor) -> torch.Tensor:
        """Embed and encode a single channel.

        Args:
            x_channel: (batch, seq_len=1800)
        Returns:
            (batch, n_patches=73, d_model=128)
        """
        patches  = self._extract_patches(x_channel)   # (B, 73, 48)
        embedded = self.patch_embed(patches)           # (B, 73, 128)
        encoded  = self.encoder(embedded)              # (B, 73, 128)
        return encoded

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def replace_head(self, new_head: nn.Module) -> None:
        """Swap the prediction head (called before each training phase)."""
        self.head = new_head

    def forward(
        self,
        x: torch.Tensor,
        mask_indices: Optional[List[int]] = None,
    ) -> torch.Tensor:
        """
        Args:
            x:            (batch, 2, 1800) — channel 0 = FHR, channel 1 = UC.
            mask_indices: list of patch indices to reconstruct; **required**
                          when head is PretrainingHead (AGW-3 fix).
        Returns:
            Pre-training head  → (batch, n_masked, patch_len=48)
            Classification head → (batch, 2)

        Raises:
            RuntimeError: if no head has been set.
            AssertionError: if PretrainingHead is active but mask_indices=None.
        """
        if self.head is None:
            raise RuntimeError(
                "No head set. Call model.replace_head(head) before forward()."
            )

        # Channel-independent encoding (shared weights)
        fhr_enc = self.encode_channel(x[:, 0, :])   # (B, 73, 128)
        uc_enc  = self.encode_channel(x[:, 1, :])   # (B, 73, 128)

        # Lazy import to avoid circular dependency
        from src.model.heads import PretrainingHead, ClassificationHead  # noqa: PLC0415

        if isinstance(self.head, PretrainingHead):
            assert mask_indices is not None, (
                "mask_indices must be provided when using PretrainingHead. "
                "AGW-3 fix: pass mask_indices explicitly through forward()."
            )
            return self.head(fhr_enc, mask_indices)

        elif isinstance(self.head, ClassificationHead):
            # Flatten each channel repr then concatenate
            # (B, 73*128) cat (B, 73*128) → (B, 18688)
            concat = torch.cat(
                [fhr_enc.flatten(start_dim=1), uc_enc.flatten(start_dim=1)],
                dim=1,
            )
            return self.head(concat)

        else:
            # Generic head: try with concatenated repr
            concat = torch.cat(
                [fhr_enc.flatten(start_dim=1), uc_enc.flatten(start_dim=1)],
                dim=1,
            )
            return self.head(concat)

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    @property
    def n_encoder_params(self) -> int:
        """Number of trainable parameters in backbone (embed + encoder)."""
        return sum(
            p.numel()
            for p in list(self.patch_embed.parameters())
            + list(self.encoder.parameters())
            if p.requires_grad
        )

    def __repr__(self) -> str:  # pragma: no cover
        head_name = type(self.head).__name__ if self.head else "None"
        return (
            f"PatchTST("
            f"patch={self.patch_len}@{self.patch_stride}, "
            f"n_patches={self.n_patches}, "
            f"d_model={self.d_model}, "
            f"head={head_name})"
        )

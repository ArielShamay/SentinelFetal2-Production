"""
masking.py — Channel-Asymmetric Masking for PatchTST Pre-training
==================================================================
Source: arXiv:2601.06149v1, Section II-D, Figure 4 (P6 fix v2)
SSOT:   docs/work_plan.md, Part ה.4 + חלק ו שלב 3.2

Algorithm (two-phase deterministic):
  Phase A: Partition target_masked (=29) into valid groups (each ≥ min_size, ≤ max_size).
  Phase B: Place groups on valid interior positions (1..n-2) without overlap.
  On placement failure → full retry (not greedy continuation).

Key properties:
  • mask[0] = mask[-1] = False  (boundary preservation — ✓ paper)
  • Every contiguous masked block has length ≥ 2  (✓ paper Figure 4)
  • sum(mask) == target_masked exactly  (mask_ratio=0.4, n=73 → 29)
  • UC never masked (asymmetric masking — ✓ paper Section II-D)
  • Zero masking: masked patch values replaced with 0.0  (✓ paper)
"""

from __future__ import annotations

import random
from typing import List, Tuple

import numpy as np


# ---------------------------------------------------------------------------
# Phase A — Partition
# ---------------------------------------------------------------------------

def _random_partition(total: int, min_size: int = 2, max_size: int = 6) -> List[int]:
    """Partition *total* into a list of groups, each in [min_size, max_size].

    Edge-case: if remaining == 1 (impossible to form a valid group), absorb
    it into the last group (groups[-1] += 1).  This preserves sum(groups) == total
    while avoiding a group of size 1.

    Args:
        total:    Number of patches to distribute (e.g. 29).
        min_size: Minimum group size (≥ 2 per paper).
        max_size: Maximum group size (≤ 6 per config).

    Returns:
        List of positive integers summing to *total*, each ≥ min_size.
    """
    groups: List[int] = []
    remaining = total
    while remaining > 0:
        if remaining < min_size:
            # Absorb remainder into last group to avoid size-1 group
            groups[-1] += remaining
            remaining = 0
        else:
            g = random.randint(min_size, min(max_size, remaining))
            # If choosing g would leave exactly 1, extend g to consume all
            if remaining - g == 1:
                g = remaining
            groups.append(g)
            remaining -= g
    return groups


# ---------------------------------------------------------------------------
# Phase B — Placement + full API
# ---------------------------------------------------------------------------

def apply_masking(
    fhr_patches: np.ndarray,
    mask_ratio: float = 0.4,
    min_group_size: int = 2,
    max_group_size: int = 6,
    max_retries: int = 100,
) -> Tuple[np.ndarray, np.ndarray]:
    """Apply contiguous-group masking to FHR patches (in-place zero-masking).

    This is the P6 fix v2 algorithm from agent_workflow.md.

    Args:
        fhr_patches:   numpy array of shape (n_patches, patch_len), e.g. (73, 48).
                       **Modified in-place**: masked positions set to 0.0.
        mask_ratio:    Fraction of FHR patches to mask (default 0.4 → 29 of 73).
        min_group_size: Minimum contiguous group length (default 2).
        max_group_size: Maximum contiguous group length (default 6).
        max_retries:   How many placement attempts before raising RuntimeError.

    Returns:
        (fhr_patches, mask_indices) where:
            fhr_patches:  same array, masked patches zeroed out.
            mask_indices: 1-D int64 ndarray of masked patch positions.

    Raises:
        RuntimeError: if placement fails after max_retries attempts.

    Guarantees (asserted):
        • mask[0] == False  (first patch never masked)
        • mask[-1] == False (last patch never masked)
        • mask.sum() == target_masked
        • Every contiguous group has length ≥ min_group_size
    """
    n = fhr_patches.shape[0]  # 73
    target_masked = round(mask_ratio * n)  # 29

    mask = np.zeros(n, dtype=bool)

    for attempt in range(max_retries):
        groups = _random_partition(target_masked, min_size=min_group_size,
                                   max_size=max_group_size)
        mask[:] = False
        success = True
        random.shuffle(groups)

        for g_len in groups:
            # Valid start positions: interior only (1..n-2), no overlap with current mask
            valid_starts = [
                s for s in range(1, n - g_len)  # n-g_len exclusive → last start = n-g_len-1
                if not mask[s:s + g_len].any()
            ]
            if not valid_starts:
                success = False
                break
            start = random.choice(valid_starts)
            mask[start : start + g_len] = True

        if success and mask.sum() == target_masked:
            break
    else:
        raise RuntimeError(
            f"Masking failed after {max_retries} retries "
            f"(n={n}, target={target_masked}, groups strategy: "
            f"min={min_group_size}, max={max_group_size})"
        )

    # --- Hard assertions (fail fast) -----------------------------------------
    assert not mask[0], "Boundary violation: first patch is masked"
    assert not mask[-1], "Boundary violation: last patch is masked"
    assert mask.sum() == target_masked, (
        f"Mask sum mismatch: got {mask.sum()}, expected {target_masked}"
    )
    # Verify every contiguous run is ≥ min_group_size
    diff = np.diff(np.concatenate([[0], mask.astype(np.int8), [0]]))
    run_starts = np.where(diff == 1)[0]
    run_ends   = np.where(diff == -1)[0]
    for s, e in zip(run_starts, run_ends):
        assert (e - s) >= min_group_size, (
            f"Group of length {e - s} < min_group_size={min_group_size} at position {s}"
        )
    # -------------------------------------------------------------------------

    # Zero masking (in-place)
    fhr_patches[mask] = 0.0

    mask_indices = np.where(mask)[0].astype(np.int64)
    return fhr_patches, mask_indices


# ---------------------------------------------------------------------------
# Stability test (run as __main__)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    N_SEEDS = 10_000
    print(f"Running masking stability test over {N_SEEDS:,} seeds…")
    dummy_patches = np.random.rand(73, 48).astype(np.float32)

    for seed in range(N_SEEDS):
        random.seed(seed)
        np.random.seed(seed)
        patches_copy = dummy_patches.copy()
        _, idx = apply_masking(patches_copy)
        # Spot-check: no boundary violation, correct count
        assert idx[0] >= 1 and idx[-1] <= 71, f"Boundary violation at seed {seed}"
        assert len(idx) == 29, f"Wrong count {len(idx)} at seed {seed}"

    print(f"✓ {N_SEEDS:,} seeds passed — masking is stable (V3.1 PASS)")

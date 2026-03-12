"""
SentinelFatal2 — Signal Preprocessing Module (O1.10)
=====================================================
Implements the preprocessing pipeline from work_plan.md (Actions A1.1, A1.2, A1.3)
based on paper Section II-B (2601.06149v1.pdf).

Constants (from work_plan.md ז.1 — MUST NOT CHANGE):
  - FHR outlier low:   50 bpm
  - FHR outlier high: 220 bpm
  - FHR clip low:      50 bpm
  - FHR clip high:    210 bpm
  - FHR normalization: (fhr - 50) / 160.0  → [0, 1]  (deviation S7)
  - UC flat window:   120 samples (30 seconds at 4 Hz)
  - UC flat std threshold: 1e-5
  - UC flat value threshold: 80 mmHg
  - UC clip:          [0, 100] mmHg
  - UC normalization: uc / 100.0  → [0, 1]
  - Output shape:     (2, T) — [0]=FHR, [1]=UC
"""

import numpy as np
import pandas as pd
import os
from typing import Optional


# ─── Constants (work_plan.md ז.1) ────────────────────────────────────────────
FHR_OUTLIER_LOW   = 50.0    # bpm — values below this are artifacts
FHR_OUTLIER_HIGH  = 220.0   # bpm — values above this are artifacts
FHR_CLIP_LOW      = 50.0    # bpm — clip floor
FHR_CLIP_HIGH     = 210.0   # bpm — clip ceiling
FHR_NORM_SHIFT    = 50.0    # (fhr - 50) / 160 maps [50,210] → [0,1]
FHR_NORM_SCALE    = 160.0   # deviation S7: (FHR-50)/160, not FHR/160

UC_FLAT_WINDOW    = 120     # samples = 30 sec at 4 Hz (Section II-B)
UC_FLAT_STD_THR   = 1e-5    # rolling std below this → flat artifact
UC_FLAT_VAL_THR   = 80.0    # flat detection only applies when uc < 80 mmHg
UC_CLIP_LOW       = 0.0     # mmHg
UC_CLIP_HIGH      = 100.0   # mmHg
UC_NORM_SCALE     = 100.0   # uc / 100 maps [0,100] → [0,1]
# ─────────────────────────────────────────────────────────────────────────────


def preprocess_fhr(raw_fhr: np.ndarray) -> np.ndarray:
    """
    Preprocess raw FHR signal (bpm) → normalized array in [0, 1].

    Pipeline (A1.1 in agent_workflow.md / Section II-B in paper):
      1. Values < 50 bpm or > 220 bpm → NaN  (artifact removal)
      2. Linear interpolation to fill NaN  (gap fill)
      3. Clip to [50, 210] bpm
      4. Normalize: (fhr - 50) / 160.0  → [0, 1]  (deviation S7)

    Parameters
    ----------
    raw_fhr : np.ndarray
        1-D array of raw FHR values in bpm (float).

    Returns
    -------
    np.ndarray
        1-D float64 array, values in [0, 1]. Shape unchanged from input.
    """
    fhr = raw_fhr.astype(np.float64).copy()

    # Step 1 — artifact removal
    fhr[fhr < FHR_OUTLIER_LOW]  = np.nan
    fhr[fhr > FHR_OUTLIER_HIGH] = np.nan

    # Step 2 — linear interpolation (fill interior gaps; edge NaNs → 0 via ffill/bfill)
    fhr = (
        pd.Series(fhr)
        .interpolate(method='linear', limit_direction='both')
        .values
    )

    # Step 3 — clip
    fhr = np.clip(fhr, FHR_CLIP_LOW, FHR_CLIP_HIGH)

    # Step 4 — normalize → [0, 1]  (deviation S7)
    fhr = (fhr - FHR_NORM_SHIFT) / FHR_NORM_SCALE

    return fhr.astype(np.float32)


def preprocess_uc(raw_uc: np.ndarray) -> np.ndarray:
    """
    Preprocess raw UC signal (mmHg) → normalized array in [0, 1].

    Pipeline (A1.2 in agent_workflow.md / Section II-B in paper):
      1. Compute rolling std (window=120, center=True)
      2. Flat mask: std < 1e-5 AND uc < 80 AND not NaN  (artifact regions)
      3. Flat regions → NaN
      4. Clip to [0, 100] mmHg
      5. Normalize: uc / 100.0  → [0, 1]
      6. Remaining NaN → 0.0

    Parameters
    ----------
    raw_uc : np.ndarray
        1-D array of raw UC values in mmHg (float).

    Returns
    -------
    np.ndarray
        1-D float32 array, values in [0, 1]. No NaN in output.
    """
    uc = raw_uc.astype(np.float64).copy()

    # Step 1-2 — flat region detection
    rolling_std = pd.Series(uc).rolling(
        window=UC_FLAT_WINDOW, center=True, min_periods=1
    ).std()
    flat_mask = (
        (rolling_std < UC_FLAT_STD_THR) &
        (uc < UC_FLAT_VAL_THR) &
        (~np.isnan(uc))
    )

    # Step 3 — mask flat regions as NaN
    uc[flat_mask] = np.nan

    # Step 4 — clip
    uc = np.clip(uc, UC_CLIP_LOW, UC_CLIP_HIGH)

    # Step 5 — normalize → [0, 1]
    # Only normalize non-NaN values (NaN stay NaN until step 6)
    mask_valid = ~np.isnan(uc)
    uc[mask_valid] /= UC_NORM_SCALE

    # Step 6 — NaN → 0.0
    uc = np.nan_to_num(uc, nan=0.0)

    return uc.astype(np.float32)


def process_and_save_recording(
    csv_path: str,
    output_path: str,
    fhr_col: str = 'fhr',
    uc_col: str = 'uc',
) -> dict:
    """
    Read a raw CTG CSV, preprocess FHR and UC, save as .npy with shape (2, T).

    Parameters
    ----------
    csv_path   : path to input CSV (columns: fhr, uc, ...)
    output_path: path to output .npy file (directory must exist)
    fhr_col    : column name for FHR signal in the CSV
    uc_col     : column name for UC signal in the CSV

    Returns
    -------
    dict with keys: 'record_id', 'shape', 'fhr_min', 'fhr_max', 'uc_min', 'uc_max',
                    'fhr_nan_count', 'uc_nan_count'
    """
    df = pd.read_csv(csv_path)

    raw_fhr = df[fhr_col].values
    raw_uc  = df[uc_col].values

    fhr_proc = preprocess_fhr(raw_fhr)
    uc_proc  = preprocess_uc(raw_uc)

    signal = np.stack([fhr_proc, uc_proc])  # shape: (2, T)
    np.save(output_path, signal)

    record_id = os.path.splitext(os.path.basename(output_path))[0]
    return {
        'record_id':    record_id,
        'shape':        signal.shape,
        'fhr_min':      float(fhr_proc.min()),
        'fhr_max':      float(fhr_proc.max()),
        'uc_min':       float(uc_proc.min()),
        'uc_max':       float(uc_proc.max()),
        'fhr_nan_count': int(np.isnan(fhr_proc).sum()),
        'uc_nan_count':  int(np.isnan(uc_proc).sum()),
    }


def batch_process_dataset(
    raw_dir: str,
    processed_dir: str,
    fname_col: str,
    id_col: str,
    metadata_df: pd.DataFrame,
    fhr_col: str = 'fhr',
    uc_col: str = 'uc',
    verbose: bool = True,
) -> list:
    """
    Process all recordings listed in metadata_df.

    Parameters
    ----------
    raw_dir       : directory containing raw CSV files
    processed_dir : directory for output .npy files
    fname_col     : metadata column containing the CSV filename
    id_col        : metadata column containing the record ID
    metadata_df   : subset of CTGDL_norm_metadata (already filtered by dataset)
    fhr_col       : CSV column name for FHR
    uc_col        : CSV column name for UC
    verbose       : if True, print progress every 50 recordings

    Returns
    -------
    list of dicts (one per recording) from process_and_save_recording
    """
    os.makedirs(processed_dir, exist_ok=True)
    results = []
    errors  = []

    for i, row in enumerate(metadata_df.itertuples(), 1):
        fname  = getattr(row, fname_col)
        rec_id = str(getattr(row, id_col))

        csv_path    = os.path.join(raw_dir, fname)
        output_path = os.path.join(processed_dir, f'{rec_id}.npy')

        try:
            result = process_and_save_recording(
                csv_path, output_path, fhr_col=fhr_col, uc_col=uc_col
            )
            results.append(result)
        except Exception as e:
            err = {'record_id': rec_id, 'csv_path': csv_path, 'error': str(e)}
            errors.append(err)
            if verbose:
                print(f"  [ERROR] {rec_id}: {e}")

        if verbose and i % 50 == 0:
            print(f"  Progress: {i}/{len(metadata_df)} processed "
                  f"({len(errors)} errors so far)")

    if verbose:
        print(f"  Done: {len(results)} OK, {len(errors)} errors")

    if errors:
        print(f"[WARNING] {len(errors)} recordings failed:")
        for e in errors:
            print(f"  {e}")

    return results

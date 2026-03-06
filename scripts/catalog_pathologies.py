"""
scripts/catalog_pathologies.py — Build God Mode pathology catalog
=================================================================

Scans all .npy recordings in data/recordings/ and identifies which recordings
contain which pathologies, and at what sample positions.

Outputs: data/god_mode_catalog.json

Usage:
    python scripts/catalog_pathologies.py
    python scripts/catalog_pathologies.py --recordings-dir data/recordings --output data/god_mode_catalog.json
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.features.clinical_extractor import (
    CLINICAL_FEATURE_NAMES,
    extract_clinical_features,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger(__name__)

# Window parameters
WINDOW_LEN = 1800   # 7.5 min at 4 Hz — matches PatchTST input
STRIDE = 900         # 50% overlap for better coverage

# Pathology detection rules (applied to the 11 clinical features)
# Each rule returns a dict of details if detected, or None
PATHOLOGY_DETECTORS: dict[str, callable] = {}


def _feat_dict(clin_list: list[float]) -> dict[str, float]:
    """Convert clinical feature list to named dict."""
    return dict(zip(CLINICAL_FEATURE_NAMES, clin_list))


def detect_late_decelerations(feats: dict[str, float]) -> dict | None:
    n = feats["n_late_decelerations"]
    if n > 0:
        return {"n_detections": int(n), "max_depth_bpm": feats["max_deceleration_depth_bpm"]}
    return None


def detect_variable_decelerations(feats: dict[str, float]) -> dict | None:
    n = feats["n_variable_decelerations"]
    if n > 0:
        return {"n_detections": int(n), "max_depth_bpm": feats["max_deceleration_depth_bpm"]}
    return None


def detect_prolonged_deceleration(feats: dict[str, float]) -> dict | None:
    n = feats["n_prolonged_decelerations"]
    if n > 0:
        return {"n_detections": int(n), "max_depth_bpm": feats["max_deceleration_depth_bpm"]}
    return None


def detect_sinusoidal_pattern(feats: dict[str, float]) -> dict | None:
    if feats["sinusoidal_detected"] > 0.5:
        return {"detected": True}
    return None


def detect_tachysystole(feats: dict[str, float]) -> dict | None:
    if feats["tachysystole_detected"] > 0.5:
        return {"detected": True}
    return None


def detect_bradycardia(feats: dict[str, float]) -> dict | None:
    if feats["is_bradycardia"] > 0.5:
        return {"baseline_bpm": feats["baseline_bpm"]}
    return None


def detect_tachycardia(feats: dict[str, float]) -> dict | None:
    if feats["is_tachycardia"] > 0.5:
        return {"baseline_bpm": feats["baseline_bpm"]}
    return None


def detect_low_variability(feats: dict[str, float]) -> dict | None:
    if feats["variability_category"] < 0.5:  # 0 = absent
        return {"amplitude_bpm": feats["variability_amplitude_bpm"]}
    return None


def detect_combined_severe(feats: dict[str, float]) -> dict | None:
    """Multiple concurrent pathologies suggesting metabolic acidemia."""
    issues = 0
    if feats["n_late_decelerations"] > 0:
        issues += 1
    if feats["variability_category"] < 1.5:  # absent or minimal
        issues += 1
    if feats["n_prolonged_decelerations"] > 0:
        issues += 1
    if feats["tachysystole_detected"] > 0.5:
        issues += 1
    if issues >= 2:
        return {
            "n_issues": issues,
            "late_decels": int(feats["n_late_decelerations"]),
            "variability_category": feats["variability_category"],
        }
    return None


PATHOLOGY_DETECTORS = {
    "late_decelerations": detect_late_decelerations,
    "variable_decelerations": detect_variable_decelerations,
    "prolonged_deceleration": detect_prolonged_deceleration,
    "sinusoidal_pattern": detect_sinusoidal_pattern,
    "tachysystole": detect_tachysystole,
    "bradycardia": detect_bradycardia,
    "tachycardia": detect_tachycardia,
    "low_variability": detect_low_variability,
    "combined_severe": detect_combined_severe,
}


def scan_recording(recording_path: Path) -> dict[str, list[dict]]:
    """Scan a single recording for all pathology types.

    Returns: {event_type: [{"start_sample": int, "details": dict}, ...]}
    """
    data = np.load(recording_path)  # (2, T) normalized
    total_samples = data.shape[1]
    results: dict[str, list[dict]] = {k: [] for k in PATHOLOGY_DETECTORS}

    if total_samples < WINDOW_LEN:
        return results

    n_windows = 0
    for start in range(0, total_samples - WINDOW_LEN + 1, STRIDE):
        window = data[:, start : start + WINDOW_LEN]
        clin_list = extract_clinical_features(window)
        feats = _feat_dict(clin_list)
        n_windows += 1

        for event_type, detector in PATHOLOGY_DETECTORS.items():
            detail = detector(feats)
            if detail is not None:
                results[event_type].append({
                    "start_sample": start,
                    "end_sample": start + WINDOW_LEN,
                    **detail,
                })

    return results


def pick_best_segment(detections: list[dict], event_type: str) -> dict | None:
    """Pick the best segment from a list of detections for a given event type."""
    if not detections:
        return None

    # Score by severity — prioritize segments with more/stronger detections
    if event_type in ("late_decelerations", "variable_decelerations"):
        detections.sort(key=lambda d: (d.get("n_detections", 0), d.get("max_depth_bpm", 0)), reverse=True)
    elif event_type == "prolonged_deceleration":
        detections.sort(key=lambda d: d.get("max_depth_bpm", 0), reverse=True)
    elif event_type == "combined_severe":
        detections.sort(key=lambda d: d.get("n_issues", 0), reverse=True)
    # For binary detections (sinusoidal, tachysystole, bradycardia, tachycardia, low_variability),
    # any detection is equally valid — just pick the first one.

    return detections[0]


def build_catalog(recordings_dir: Path) -> dict:
    """Scan all recordings and build the pathology catalog."""
    npy_files = sorted(recordings_dir.glob("*.npy"))
    if not npy_files:
        log.error("No .npy files found in %s", recordings_dir)
        sys.exit(1)

    log.info("Scanning %d recordings in %s ...", len(npy_files), recordings_dir)

    catalog: dict[str, list[dict]] = {k: [] for k in PATHOLOGY_DETECTORS}

    for i, path in enumerate(npy_files):
        recording_id = path.stem
        log.info("[%d/%d] Scanning %s ...", i + 1, len(npy_files), recording_id)

        try:
            results = scan_recording(path)
        except Exception as exc:
            log.warning("  Failed to scan %s: %s", recording_id, exc)
            continue

        for event_type, detections in results.items():
            if detections:
                best = pick_best_segment(detections, event_type)
                if best is not None:
                    entry = {
                        "recording_id": recording_id,
                        "best_start_sample": best["start_sample"],
                        "window_count": len(detections),
                    }
                    # Include type-specific details
                    for k, v in best.items():
                        if k not in ("start_sample", "end_sample"):
                            entry[k] = v
                    catalog[event_type].append(entry)

    # Sort each event type by relevance (window_count desc as general proxy)
    for event_type in catalog:
        catalog[event_type].sort(key=lambda e: e.get("window_count", 0), reverse=True)

    return catalog


def main():
    parser = argparse.ArgumentParser(description="Build God Mode pathology catalog")
    parser.add_argument(
        "--recordings-dir",
        type=Path,
        default=PROJECT_ROOT / "data" / "recordings",
        help="Path to directory containing .npy recording files",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "data" / "god_mode_catalog.json",
        help="Output path for the catalog JSON file",
    )
    args = parser.parse_args()

    catalog = build_catalog(args.recordings_dir)

    # Summary
    log.info("=" * 60)
    log.info("Catalog summary:")
    for event_type, entries in catalog.items():
        log.info("  %-28s %3d recordings", event_type, len(entries))
    log.info("=" * 60)

    # Check for gaps
    missing = [k for k, v in catalog.items() if not v]
    if missing:
        log.warning(
            "No recordings found for: %s — feature override will be used as fallback",
            ", ".join(missing),
        )

    output = {
        "version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "recordings_dir": str(args.recordings_dir),
        "catalog": catalog,
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    log.info("Catalog written to %s", args.output)


if __name__ == "__main__":
    main()

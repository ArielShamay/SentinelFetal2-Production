"""
scripts/detection_accuracy_test.py — God Mode detection accuracy benchmark.

Streams each recording from data/god_mode_catalog.json through the FULL
SentinelFetal2 pipeline (PatchTST + clinical rules + LR meta-classifier)
with NO god mode overrides, and measures:

  1. Detection rate   — what % of recordings trigger alert=True?
  2. Detection latency — seconds from pathology start (best_start_sample)
                         to first alert (accounts for 7.5-min warmup).
  3. End detection    — after the recording ends, does the alert resolve
                         when padded with 7.5 min of normal-range signal?

Usage:
    python scripts/detection_accuracy_test.py               # all recordings
    python scripts/detection_accuracy_test.py --max-per-type 5  # quick sample
    python scripts/detection_accuracy_test.py --event-type late_decelerations
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import numpy as np

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_WINDOW_LEN = 1800          # samples before first inference (7.5 min @ 4 Hz)
_NORMAL_FHR = 0.625         # 150 bpm normalized: (150 - 50) / 160
_NORMAL_UC  = 0.0           # 0 mmHg (no contraction)
_PAD_SAMPLES = 1800         # 7.5 min of normal padding for end-detection test
_SLOW_LATENCY_S = 120.0     # threshold for "slow detection" in outlier report
_RECORDINGS_DIR = Path("data/recordings")
_CATALOG_PATH   = Path("data/god_mode_catalog.json")
_ARTIFACTS_DIR  = Path("artifacts")
_LOGS_DIR       = Path("logs")


# ---------------------------------------------------------------------------
# Result dataclass per recording
# ---------------------------------------------------------------------------

@dataclass
class RecordingResult:
    event_type: str
    recording_id: str
    best_start_sample: int
    recording_len: int           # total samples in file
    detected: bool = False
    detection_sample: int = -1   # absolute sample index of first alert
    detection_latency_s: float = -1.0   # seconds after effective_start
    resolved: bool = False
    resolve_latency_s: float = -1.0     # seconds from recording end to resolution
    skip_reason: str = ""        # non-empty → was skipped
    peak_risk: float = 0.0       # highest risk_score seen during pathology window


# ---------------------------------------------------------------------------
# Model loading
# ---------------------------------------------------------------------------

def load_models_and_config() -> tuple[list, object, object, dict]:
    """Load all production artifacts once. Returns (models, scaler, lr, config)."""
    print("Loading production_config.json ...")
    with open(_ARTIFACTS_DIR / "production_config.json", encoding="utf-8") as f:
        config = json.load(f)

    print("Loading PatchTST models (this takes ~10 seconds) ...")
    from src.inference.pipeline import _load_production_models, _load_scaler_and_lr
    models = _load_production_models(config)
    scaler, lr_model = _load_scaler_and_lr()
    print(f"  Loaded {len(models)} PatchTST folds, scaler={type(scaler).__name__}, "
          f"lr={type(lr_model).__name__}")
    return models, scaler, lr_model, config


# ---------------------------------------------------------------------------
# Per-recording test
# ---------------------------------------------------------------------------

def test_recording(
    recording_id: str,
    event_type: str,
    best_start_sample: int,
    models: list,
    scaler,
    lr_model,
    config: dict,
    recordings_dir: Path = _RECORDINGS_DIR,
) -> RecordingResult:
    """Stream one recording through SentinelRealtime and measure detection."""
    from src.inference.pipeline import SentinelRealtime

    result = RecordingResult(
        event_type=event_type,
        recording_id=recording_id,
        best_start_sample=best_start_sample,
        recording_len=0,
    )

    # --- Load .npy file ---
    npy_path = recordings_dir / f"{recording_id}.npy"
    if not npy_path.exists():
        result.skip_reason = "file_missing"
        return result

    data = np.load(npy_path)
    if data.ndim != 2 or data.shape[0] != 2:
        result.skip_reason = f"bad_shape_{data.shape}"
        return result

    fhr_arr = data[0].astype(np.float32)
    uc_arr  = data[1].astype(np.float32)
    T = len(fhr_arr)
    result.recording_len = T

    # Handle NaN
    fhr_arr = np.nan_to_num(fhr_arr, nan=_NORMAL_FHR)
    uc_arr  = np.nan_to_num(uc_arr,  nan=_NORMAL_UC)

    # The pipeline cannot produce an inference until _WINDOW_LEN samples are
    # buffered, so detection before that sample is impossible regardless of
    # where the pathology starts.
    effective_start = max(best_start_sample, _WINDOW_LEN)

    # If the recording is too short to reach effective_start, skip it.
    if T <= effective_start:
        result.skip_reason = f"too_short_{T}_samples"
        return result

    # --- Create a fresh pipeline (god_mode=False — no overrides) ---
    pipeline = SentinelRealtime(
        bed_id="benchmark_bed",
        recording_id=recording_id,
        config=config,
        models=models,
        scaler=scaler,
        lr_model=lr_model,
        god_mode=False,
        inference_offset=0,
    )

    # --- Phase 1: stream the recording ---
    first_alert_sample: int | None = None
    peak_risk = 0.0

    for i in range(T):
        state = pipeline.on_new_sample(float(fhr_arr[i]), float(uc_arr[i]))
        if state is None:
            continue
        if i >= effective_start:
            if state.risk_score > peak_risk:
                peak_risk = state.risk_score
            if state.alert and first_alert_sample is None:
                first_alert_sample = i

    result.peak_risk = peak_risk

    if first_alert_sample is not None:
        result.detected = True
        result.detection_sample = first_alert_sample
        result.detection_latency_s = (first_alert_sample - effective_start) / 4.0

    # --- Phase 2: pad with normal signal to test end-detection ---
    # Only run if we're already in alert state at end of recording, OR
    # if detection happened within the recording (to see if it resolves).
    resolved_sample: int | None = None

    for j in range(_PAD_SAMPLES):
        state = pipeline.on_new_sample(_NORMAL_FHR, _NORMAL_UC)
        if state is None:
            continue
        if not state.alert:
            resolved_sample = T + j
            break

    if resolved_sample is not None:
        result.resolved = True
        result.resolve_latency_s = (resolved_sample - T) / 4.0

    return result


# ---------------------------------------------------------------------------
# Catalog loading and grouping
# ---------------------------------------------------------------------------

def load_catalog(event_type_filter: str | None) -> dict[str, list[dict]]:
    """Returns {event_type: [catalog_entry, ...]}."""
    with open(_CATALOG_PATH, encoding="utf-8") as f:
        data = json.load(f)

    # Catalog is structured as {"catalog": {event_type: [entries...]}}
    raw: dict = data["catalog"] if "catalog" in data else data

    groups: dict[str, list[dict]] = {}
    for et, entries in raw.items():
        if event_type_filter and et != event_type_filter:
            continue
        groups[et] = list(entries)

    return groups


# ---------------------------------------------------------------------------
# Reporting helpers
# ---------------------------------------------------------------------------

def _safe_mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else float("nan")

def _safe_min(values: list[float]) -> float:
    return min(values) if values else float("nan")

def _safe_max(values: list[float]) -> float:
    return max(values) if values else float("nan")

def _fmt(v: float, decimals: int = 1) -> str:
    if v != v:  # NaN
        return "  n/a"
    return f"{v:>{6}.{decimals}f}"


def build_report(all_results: list[RecordingResult], elapsed_sec: float, config: dict) -> str:
    threshold = config.get("decision_threshold", 0.4605)
    lines: list[str] = []

    lines.append("")
    lines.append("=" * 78)
    lines.append("  SentinelFetal2 — God Mode Detection Accuracy Report")
    lines.append(f"  Run: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  "
                 f"Total elapsed: {elapsed_sec/60:.1f} min")
    lines.append(f"  Alert threshold: risk_score > {threshold:.4f} ({threshold*100:.2f}%)")
    lines.append("=" * 78)

    # --- Group by event_type ---
    by_type: dict[str, list[RecordingResult]] = defaultdict(list)
    for r in all_results:
        by_type[r.event_type].append(r)

    # Header
    col = "{:<26} {:>7} {:>7} {:>8} {:>9} {:>9} {:>9} {:>9} {:>9}"
    lines.append("")
    lines.append(col.format(
        "Event Type", "Tested", "Detectd", "Rate%",
        "Lat avg", "Lat min", "Lat max",
        "Resolvd%", "Res avg",
    ))
    lines.append("-" * 78)

    total_tested = total_detected = total_resolved = 0
    all_latencies: list[float] = []
    all_resolve: list[float] = []

    for et in sorted(by_type.keys()):
        results = by_type[et]
        tested   = [r for r in results if not r.skip_reason]
        detected = [r for r in tested  if r.detected]
        resolved = [r for r in tested  if r.resolved]

        latencies = [r.detection_latency_s for r in detected]
        resolves  = [r.resolve_latency_s   for r in resolved]

        n_t = len(tested)
        n_d = len(detected)
        n_r = len(resolved)
        rate = (n_d / n_t * 100) if n_t > 0 else float("nan")
        res_pct = (n_r / n_t * 100) if n_t > 0 else float("nan")

        total_tested   += n_t
        total_detected += n_d
        total_resolved += n_r
        all_latencies.extend(latencies)
        all_resolve.extend(resolves)

        lines.append(col.format(
            et[:26],
            n_t, n_d,
            f"{rate:>7.1f}",
            _fmt(_safe_mean(latencies)), _fmt(_safe_min(latencies)), _fmt(_safe_max(latencies)),
            f"{res_pct:>8.1f}", _fmt(_safe_mean(resolves)),
        ))

    lines.append("-" * 78)
    total_rate = (total_detected / total_tested * 100) if total_tested > 0 else 0
    res_pct_all = (total_resolved / total_tested * 100) if total_tested > 0 else 0
    lines.append(col.format(
        "TOTAL", total_tested, total_detected,
        f"{total_rate:>7.1f}",
        _fmt(_safe_mean(all_latencies)), _fmt(_safe_min(all_latencies)), _fmt(_safe_max(all_latencies)),
        f"{res_pct_all:>8.1f}", _fmt(_safe_mean(all_resolve)),
    ))
    lines.append("")
    lines.append("Columns: Lat = detection latency (seconds after pathology start)")
    lines.append("         Resolvd% = recordings where alert cleared after padding with 7.5 min normal CTG")
    lines.append("         Res avg = avg seconds from recording end until alert resolved")

    # --- Skipped recordings ---
    skipped = [r for r in all_results if r.skip_reason]
    if skipped:
        lines.append("")
        lines.append(f"--- Skipped recordings ({len(skipped)}) ---")
        skip_counts: dict[str, int] = defaultdict(int)
        for r in skipped:
            skip_counts[r.skip_reason] += 1
        for reason, count in sorted(skip_counts.items()):
            lines.append(f"  {reason}: {count}")

    # --- Outliers: missed or slow ---
    missed = [r for r in all_results if not r.skip_reason and not r.detected]
    slow   = [r for r in all_results if not r.skip_reason and r.detected
              and r.detection_latency_s > _SLOW_LATENCY_S]

    if missed:
        lines.append("")
        lines.append(f"--- Missed detections ({len(missed)}) ---")
        lines.append("  {:<12} {:<28} {:>10} {:>8}".format(
            "Recording", "Event Type", "PathStart", "Len(s)"))
        for r in sorted(missed, key=lambda x: x.event_type)[:50]:
            lines.append("  {:<12} {:<28} {:>10} {:>8.0f}".format(
                r.recording_id, r.event_type[:28],
                r.best_start_sample, r.recording_len / 4.0,
            ))
        if len(missed) > 50:
            lines.append(f"  ... and {len(missed) - 50} more")

    if slow:
        lines.append("")
        lines.append(f"--- Slow detections (latency > {_SLOW_LATENCY_S:.0f}s) ({len(slow)}) ---")
        lines.append("  {:<12} {:<28} {:>12}".format("Recording", "Event Type", "Latency(s)"))
        for r in sorted(slow, key=lambda x: -x.detection_latency_s)[:30]:
            lines.append("  {:<12} {:<28} {:>12.1f}".format(
                r.recording_id, r.event_type[:28], r.detection_latency_s))

    lines.append("")
    lines.append("=" * 78)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Stream god_mode_catalog recordings through the full pipeline and measure detection accuracy."
    )
    parser.add_argument(
        "--max-per-type", type=int, default=None, metavar="N",
        help="Test at most N recordings per event type (default: all)"
    )
    parser.add_argument(
        "--event-type", type=str, default=None,
        help="Only test one event type (e.g. late_decelerations)"
    )
    parser.add_argument(
        "--recordings-dir", type=Path, default=_RECORDINGS_DIR,
        help=f"Path to .npy recordings (default: {_RECORDINGS_DIR})"
    )
    args = parser.parse_args()

    # Run from project root so relative paths resolve correctly
    project_root = Path(__file__).resolve().parent.parent
    os.chdir(project_root)
    sys.path.insert(0, str(project_root))

    recordings_dir = args.recordings_dir

    if not _CATALOG_PATH.exists():
        print(f"[ERROR] Catalog not found: {_CATALOG_PATH}", file=sys.stderr)
        sys.exit(1)

    # Load models once
    t0 = time.time()
    models, scaler, lr_model, config = load_models_and_config()
    load_time = time.time() - t0
    print(f"  Models loaded in {load_time:.1f}s\n")

    # Load catalog and group
    groups = load_catalog(args.event_type)
    if not groups:
        print("[ERROR] No matching entries in catalog.", file=sys.stderr)
        sys.exit(1)

    # Determine total work
    plan: list[tuple[str, dict]] = []
    for et, entries in sorted(groups.items()):
        subset = entries if args.max_per_type is None else entries[:args.max_per_type]
        for entry in subset:
            plan.append((et, entry))

    total = len(plan)
    print(f"Testing {total} recordings across {len(groups)} event type(s) ...")
    if args.max_per_type:
        print(f"  (limited to {args.max_per_type} per type)\n")

    # Run tests
    all_results: list[RecordingResult] = []
    t_start = time.time()

    for idx, (et, entry) in enumerate(plan, 1):
        rid = str(entry["recording_id"])
        bss = int(entry.get("best_start_sample", 0))

        eta_str = ""
        if idx > 1:
            elapsed = time.time() - t_start
            rate = (idx - 1) / elapsed
            remaining = (total - idx + 1) / rate if rate > 0 else 0
            eta_str = f"  ETA {remaining/60:.1f}min"

        print(f"  [{idx:4d}/{total}] {et:<28} rid={rid:<8} start={bss:>6}{eta_str}",
              end="", flush=True)

        t_rec = time.time()
        result = test_recording(rid, et, bss, models, scaler, lr_model, config, recordings_dir)
        rec_time = time.time() - t_rec
        all_results.append(result)

        if result.skip_reason:
            print(f"  SKIP ({result.skip_reason})")
        elif result.detected:
            print(f"  ALERT @ {result.detection_sample}s  "
                  f"lat={result.detection_latency_s:.0f}s  "
                  f"peak={result.peak_risk*100:.0f}%  "
                  f"{'resolved' if result.resolved else 'persists'}  "
                  f"[{rec_time:.1f}s]")
        else:
            print(f"  MISSED  peak={result.peak_risk*100:.0f}%  [{rec_time:.1f}s]")

    total_elapsed = time.time() - t_start
    print(f"\nDone. {total} recordings in {total_elapsed/60:.1f} min.\n")

    # Build and print report
    report = build_report(all_results, total_elapsed, config)
    print(report)

    # Save to logs/
    _LOGS_DIR.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = _LOGS_DIR / f"detection_accuracy_{ts}.txt"
    log_path.write_text(report, encoding="utf-8")
    print(f"Report saved to {log_path}\n")


if __name__ == "__main__":
    main()

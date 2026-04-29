"""
scripts/validate_artifacts.py — Build-time artifact validation (§11.14).

Validates all required model artifacts before deployment.
Exits with code 1 if any artifact is missing or malformed.

Usage:
    python scripts/validate_artifacts.py
    python scripts/validate_artifacts.py --artifacts-dir artifacts --weights-dir weights
"""
from __future__ import annotations

import argparse
import json
import pickle
import sys
from pathlib import Path

# Expected fields in production_config.json
_REQUIRED_CONFIG_KEYS = {
    "best_at",
    "decision_threshold",
    "inference_stride",
    "n_features",
    "n_folds",
    "weights",
    "feature_names",
}

_EXPECTED_FEATURE_COUNT = 25
_EXPECTED_N_FOLDS = 5


def _fail(msg: str) -> None:
    print(f"[FAIL] {msg}", file=sys.stderr)
    sys.exit(1)


def _ok(msg: str) -> None:
    print(f"[ OK ] {msg}")


def validate_production_config(artifacts_dir: Path) -> dict:
    path = artifacts_dir / "production_config.json"
    if not path.exists():
        _fail(f"production_config.json not found at {path}")

    with open(path, encoding="utf-8") as f:
        cfg = json.load(f)

    missing = _REQUIRED_CONFIG_KEYS - cfg.keys()
    if missing:
        _fail(f"production_config.json missing keys: {missing}")

    if cfg["n_features"] != _EXPECTED_FEATURE_COUNT:
        _fail(
            f"n_features={cfg['n_features']} expected {_EXPECTED_FEATURE_COUNT}"
        )

    if cfg["n_folds"] != _EXPECTED_N_FOLDS:
        _fail(f"n_folds={cfg['n_folds']} expected {_EXPECTED_N_FOLDS}")

    if len(cfg["feature_names"]) != _EXPECTED_FEATURE_COUNT:
        _fail(
            f"feature_names has {len(cfg['feature_names'])} entries, "
            f"expected {_EXPECTED_FEATURE_COUNT}"
        )

    _ok(
        f"production_config.json — n_features={cfg['n_features']}, "
        f"n_folds={cfg['n_folds']}, threshold={cfg['decision_threshold']:.4f}"
    )
    return cfg


def validate_weights(weights: list[str], weights_dir: Path | None = None) -> None:
    import torch
    for path_str in weights:
        path = Path(path_str)
        if weights_dir is not None and not path.is_absolute():
            path = weights_dir / path.name
        if not path.exists():
            _fail(f"Weight file not found: {path}")
        try:
            state = torch.load(path, map_location="cpu", weights_only=True)
            if not isinstance(state, dict) or len(state) == 0:
                _fail(f"Weight file {path} loads but state dict is empty or invalid")
        except Exception as exc:
            _fail(f"torch.load failed for {path}: {exc}")

        size_mb = path.stat().st_size / (1024 * 1024)
        _ok(f"Weight {path.name} — {size_mb:.1f} MB, {len(state)} keys")


def validate_sklearn_artifact(path: Path, name: str) -> None:
    if not path.exists():
        _fail(f"{name} not found at {path}")

    try:
        with open(path, "rb") as f:
            obj = pickle.load(f)  # noqa: S301 — controlled internal artifact
    except Exception as exc:
        _fail(f"Failed to load {name}: {exc}")

    _ok(f"{name} — type={type(obj).__name__}")


def validate_recordings_dir(recordings_dir: Path) -> None:
    if not recordings_dir.exists():
        _fail(f"Recordings directory not found: {recordings_dir}")

    npy_files = list(recordings_dir.glob("*.npy"))
    if not npy_files:
        _fail(f"No .npy files found in {recordings_dir}")

    # Spot-check first file
    first = npy_files[0]
    try:
        import numpy as np
        data = np.load(first)
        if data.ndim != 2 or data.shape[0] != 2:
            _fail(
                f"Recording {first.name} has unexpected shape {data.shape} "
                "(expected (2, T) with channel 0=FHR, channel 1=UC)"
            )
    except Exception as exc:
        _fail(f"Failed to load recording {first.name}: {exc}")

    _ok(f"Recordings directory — {len(npy_files)} .npy files found")


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate SentinelFetal2 production artifacts")
    parser.add_argument("--artifacts-dir", default="artifacts", type=Path)
    parser.add_argument("--weights-dir", default="weights", type=Path)
    parser.add_argument("--recordings-dir", default="data/recordings", type=Path)
    parser.add_argument("--validate-recordings", action="store_true",
                        help="Also validate recording directory (requires mounted data volume)")
    args = parser.parse_args()

    artifacts_dir: Path = args.artifacts_dir
    print(f"\nValidating artifacts in: {artifacts_dir.resolve()}\n")

    # 1. production_config.json
    cfg = validate_production_config(artifacts_dir)

    # 2. Weight files (from config, optionally rooted at --weights-dir)
    validate_weights(cfg["weights"], args.weights_dir)

    # 3. Scaler
    validate_sklearn_artifact(artifacts_dir / "production_scaler.pkl", "production_scaler.pkl")

    # 4. LR model
    validate_sklearn_artifact(artifacts_dir / "production_lr.pkl", "production_lr.pkl")

    # 5. Recordings directory (opt-in — Docker volume not available at build time)
    if args.validate_recordings:
        validate_recordings_dir(args.recordings_dir)

    print("\n[OK] All artifacts valid.\n")


if __name__ == "__main__":
    main()

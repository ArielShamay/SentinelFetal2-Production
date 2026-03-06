"""
api/services/model_loader.py — Load production ML artifacts once at startup.

Returns:
    models  : list[PatchTST]        5 fold models, eval mode, ClassificationHead attached
    scaler  : StandardScaler        25-feature scaler
    lr_model: LogisticRegression    meta-classifier
    config  : dict                  production_config.json
"""
from __future__ import annotations

import json
import logging
import pickle
import time
from pathlib import Path

import torch

logger = logging.getLogger(__name__)


def load_production_models(
    artifacts_dir: Path = Path("artifacts"),
    weights_dir: Path = Path("weights"),
    config_path: Path = Path("config/train_config.yaml"),
) -> tuple:
    """
    Load all production ML artifacts.

    Returns (models, scaler, lr_model, prod_cfg).

    Raises RuntimeError on any failure — lifespan should not start if this fails.
    """
    t0 = time.time()

    # ── production_config.json ────────────────────────────────────────────
    cfg_path = artifacts_dir / "production_config.json"
    try:
        with open(cfg_path, encoding="utf-8") as f:
            prod_cfg = json.load(f)
    except Exception as exc:
        raise RuntimeError(f"Cannot load production_config.json: {exc}") from exc

    logger.info("Loaded production_config.json (n_folds=%d)", prod_cfg["n_folds"])

    # ── PatchTST fold models ──────────────────────────────────────────────
    from src.model.patchtst import PatchTST, load_config
    from src.model.heads import ClassificationHead

    try:
        train_cfg = load_config(str(config_path))
    except Exception as exc:
        raise RuntimeError(f"Cannot load train_config.yaml: {exc}") from exc

    models = []
    for fold in range(prod_cfg["n_folds"]):
        weight_path = Path(prod_cfg["weights"][fold])
        logger.info("Loading fold %d from %s …", fold, weight_path)
        try:
            model = PatchTST(train_cfg)
            # ⚠ REQUIRED: attach ClassificationHead BEFORE load_state_dict
            # d_in = n_patches(73) * d_model(128) * n_channels(2) = 18688
            model.replace_head(ClassificationHead(d_in=18688, n_classes=2, dropout=0.2))
            state = torch.load(weight_path, map_location="cpu", weights_only=True)
            model.load_state_dict(state)
            model.eval()
            models.append(model)
        except Exception as exc:
            raise RuntimeError(f"Failed to load fold {fold} from {weight_path}: {exc}") from exc

    logger.info("Loaded %d PatchTST fold models", len(models))

    # ── StandardScaler ────────────────────────────────────────────────────
    scaler_path = artifacts_dir / "production_scaler.pkl"
    try:
        with open(scaler_path, "rb") as f:
            scaler = pickle.load(f)
    except Exception as exc:
        raise RuntimeError(f"Cannot load production_scaler.pkl: {exc}") from exc

    # ── LogisticRegression ────────────────────────────────────────────────
    lr_path = artifacts_dir / "production_lr.pkl"
    try:
        with open(lr_path, "rb") as f:
            lr_model = pickle.load(f)
    except Exception as exc:
        raise RuntimeError(f"Cannot load production_lr.pkl: {exc}") from exc

    elapsed = time.time() - t0
    logger.info(
        "Model loading complete in %.2fs (scaler=%s, lr=%s)",
        elapsed, type(scaler).__name__, type(lr_model).__name__,
    )
    return models, scaler, lr_model, prod_cfg

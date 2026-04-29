"""src/inference/pipeline.py — SentinelFetal2 Real-Time Inference Pipeline
==========================================================================

Glue layer connecting:
  - src/inference/alert_extractor.py   → 12 AI features
  - src/features/clinical_extractor.py → 11 clinical features
  - artifacts/production_scaler.pkl + production_lr.pkl → risk_score

PLAN.md references: §1, §2, §10.6, §10.7, §11.1, §11.4, §11.15
AGENTS.md Phase 1 deliverable.

Bug fixes implemented:
  BUG-3  current_sample_count as @property
  BUG-5  threading.Lock guards ring buffers + window_scores
  BUG-6  _run_ensemble try/except + None fallback
  BUG-7  fhr_latest / uc_latest use [-24:] not [-16:]
  BUG-8  no self._loop stored (caller submits to ThreadPoolExecutor)

Normalization invariant:
  Ring buffers hold NORMALIZED values [0,1] throughout.
    FHR: norm = (bpm - 50) / 160   ↔   bpm = norm * 160 + 50
    UC:  norm = mmHg / 100          ↔   mmHg = norm * 100
  Denormalization is ONLY for UI display (fhr_latest, uc_latest).
"""

from __future__ import annotations

import logging
import pickle
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants (match production_config.json exactly)
# ---------------------------------------------------------------------------

_WINDOW_LEN = 1800          # PatchTST input length: 7.5 min × 4 Hz
_RING_MAXLEN = 7200         # ring buffer capacity: 30 min × 4 Hz
_INFERENCE_STRIDE = 24      # production_config["inference_stride"]; one inference every 6 seconds
_WINDOW_SCORE_MAX = 300     # cap window_scores: ~30 min of inference history
_DEFAULT_DECISION_THRESHOLD = 0.4605492604713227   # production_config["decision_threshold"]
_DEFAULT_BEST_AT = 0.5                             # production_config["best_at"]

# ---------------------------------------------------------------------------
# BedState — snapshot emitted every 6 seconds per bed
# ---------------------------------------------------------------------------


@dataclass
class BedState:
    """State snapshot for one bed, emitted every 6 seconds.

    Field names for clinical features MUST match CLINICAL_FEATURE_NAMES in
    clinical_extractor.py and feature_names order in production_config.json.
    Fields marked (§X.Y) are additions from PLAN.md sections beyond §2.
    """

    # ── Identity ──────────────────────────────────────────────────────────
    bed_id: str                              # e.g. "bed_01"
    recording_id: str                        # e.g. "1023"
    timestamp: float                         # Unix time of this snapshot

    # ── AI Model Output ───────────────────────────────────────────────────
    risk_score: float                        # LR output [0, 1]
    alert: bool                              # risk_score > alert_threshold
    alert_threshold: float                   # decision_threshold from config
    window_prob: float                       # latest PatchTST window P(acidemia)

    # ── Display values (denormalized for UI) ──────────────────────────────
    # Must send exactly STRIDE=24 values per tick to avoid gaps in CTG graph.
    # BUG-7: [-24:] not [-16:] — 8 silent data points dropped per tick at [-16:]
    fhr_latest: list                         # last 24 FHR values in BPM (norm*160+50)
    uc_latest: list                          # last 24 UC values in mmHg (norm*100)

    # ── Clinical Features (exact CLINICAL_FEATURE_NAMES order) ────────────
    baseline_bpm: float                      # [0]
    is_tachycardia: float                    # [1]  0 or 1
    is_bradycardia: float                    # [2]  0 or 1
    variability_amplitude_bpm: float         # [3]
    variability_category: float              # [4]  0=absent 1=minimal 2=moderate 3=marked
    n_late_decelerations: int                # [5]
    n_variable_decelerations: int            # [6]
    n_prolonged_decelerations: int           # [7]
    max_deceleration_depth_bpm: float        # [8]
    sinusoidal_detected: bool                # [9]
    tachysystole_detected: bool              # [10]

    # ── Playback ──────────────────────────────────────────────────────────
    elapsed_seconds: float                   # recording position in seconds
    warmup: bool                             # True while < 1800 samples buffered
    sample_count: int                        # total samples processed

    # ── God Mode (§10.7) — optional, default off ──────────────────────────
    god_mode_active: bool = False
    active_events: list = field(default_factory=list)   # list[EventAnnotation]

    # ── Risk Trend (§11.15) ───────────────────────────────────────────────
    risk_delta: float = 0.0                  # risk_score[-1] - risk_score[-4] (~24 sec)

    # ── Explainability (ISSUE-10 layers 1-3) ──────────────────────────────
    top_contributions: list = field(default_factory=list)
    detection_events: list = field(default_factory=list)

    # ── Stale Detection (§11.4) ───────────────────────────────────────────
    last_update_server_ts: float = field(default_factory=time.time)


# ---------------------------------------------------------------------------
# Model loading helpers (lazy — only called when models not provided)
# ---------------------------------------------------------------------------


def _load_production_models(config: dict) -> list:
    """Load 5-fold PatchTST ensemble from production_config weights paths.

    Called once per SentinelRealtime instance when models=None.
    For multi-bed deployments, prefer loading once via model_loader.py and
    passing the pre-loaded list to every SentinelRealtime instance.
    """
    import torch
    from src.model.heads import ClassificationHead
    from src.model.patchtst import PatchTST, load_config

    train_cfg = load_config("config/train_config.yaml")
    models: list = []
    for weight_path in config["weights"]:
        model = PatchTST(train_cfg)
        # REQUIRED: attach ClassificationHead BEFORE load_state_dict.
        # Checkpoint contains head.linear.* — PatchTST.head defaults to None.
        # d_in = n_patches(73) × d_model(128) × n_channels(2) = 18 688
        model.replace_head(ClassificationHead(d_in=18_688, n_classes=2, dropout=0.2))
        state = torch.load(weight_path, map_location="cpu", weights_only=True)
        model.load_state_dict(state)
        model.eval()
        models.append(model)
    logger.info(f"Loaded {len(models)} PatchTST fold models.")
    return models


def _load_scaler_and_lr() -> tuple[Any, Any]:
    """Load StandardScaler and LogisticRegression from artifact files."""
    with open("artifacts/production_scaler.pkl", "rb") as f:
        scaler = pickle.load(f)
    with open("artifacts/production_lr.pkl", "rb") as f:
        lr_model = pickle.load(f)
    return scaler, lr_model


# ---------------------------------------------------------------------------
# SentinelRealtime — single-bed inference pipeline
# ---------------------------------------------------------------------------


class SentinelRealtime:
    """Single-bed real-time inference pipeline.

    Receives NORMALIZED FHR/UC samples at 4 Hz:
        FHR: [0, 1] = (bpm - 50) / 160
        UC:  [0, 1] = mmHg / 100
    (Values are stored in .npy files already normalized by preprocessing.py.)

    Emits BedState every 24 samples (6 sec) once ring buffer has >= 1800 samples.
    Returns None during warmup (< 1800 samples) or on non-inference ticks.

    Thread safety (BUG-5):
        _state_lock guards ring buffers, window_scores, sample_count, risk_history.
        on_new_sample() is called from ThreadPoolExecutor workers — lock is held
        for the full duration of the call including PatchTST inference (~50ms).
        reset() also acquires the lock, so it blocks until inference finishes.

    Usage (multi-bed deployment — recommended):
        models, scaler, lr, cfg = load_production_models()   # once at startup
        p = SentinelRealtime("bed_01", "1023", config=cfg,
                             models=models, scaler=scaler, lr_model=lr)
        for fhr_norm, uc_norm in stream_at_4hz():
            state = p.on_new_sample(fhr_norm, uc_norm)
            if state:
                broadcast(state)

    Usage (standalone / test — models loaded automatically):
        import json
        with open("artifacts/production_config.json") as f:
            cfg = json.load(f)
        p = SentinelRealtime("bed_01", "1023", config=cfg)
    """

    def __init__(
        self,
        bed_id: str,
        recording_id: str,
        config: dict,                        # production_config.json contents
        models: list | None = None,          # 5 PatchTST instances (eval mode)
        scaler: Any | None = None,           # StandardScaler, 25 features
        lr_model: Any | None = None,         # LogisticRegression
        god_mode: bool = False,              # enable God Mode for this bed
        inference_offset: int = 0,           # stagger offset within _INFERENCE_STRIDE
    ) -> None:
        self._bed_id = bed_id
        self._recording_id = recording_id
        self._config = config

        # ── Model loading (lazy if not provided) ──────────────────────────
        if models is None:
            models = _load_production_models(config)
        if scaler is None or lr_model is None:
            _scaler, _lr = _load_scaler_and_lr()
            scaler = scaler if scaler is not None else _scaler
            lr_model = lr_model if lr_model is not None else _lr

        self._models = models
        self._scaler = scaler
        self._lr = lr_model
        self._feature_names: list[str] = list(config.get("feature_names", []))
        if len(self._feature_names) != 25:
            logger.warning(
                "[%s] production_config feature_names missing/invalid; "
                "explainability contributions will use positional names.",
                bed_id,
            )
            self._feature_names = [f"feature_{i}" for i in range(25)]

        configured_stride = int(config.get("inference_stride", _INFERENCE_STRIDE))
        if configured_stride != _INFERENCE_STRIDE:
            raise ValueError(
                f"production_config inference_stride={configured_stride} "
                f"does not match runtime stride {_INFERENCE_STRIDE}"
            )

        # ── Inference stagger — spreads N beds across one stride window ───
        # bed i fires inference when (count - offset) % stride == 0, so
        # beds 0..N-1 fire 1 sample apart instead of all at once.
        self._inference_offset: int = inference_offset % _INFERENCE_STRIDE

        # ── Ring buffers: normalized [0,1] values ─────────────────────────
        self._fhr_ring: deque = deque(maxlen=_RING_MAXLEN)
        self._uc_ring: deque = deque(maxlen=_RING_MAXLEN)
        self._sample_count: int = 0

        # ── Accumulated window scores: [(start_sample, prob), ...] ────────
        # Grows over time — each new window appends one entry.
        # All entries used by extract_recording_features for AI feature set.
        self._window_scores: list[tuple[int, float]] = []

        # ── Risk history for delta computation (§11.15) ───────────────────
        # Stores recent risk scores; risk_delta = latest - score from 4 ticks ago (~24s).
        self._risk_history: list[float] = []

        # ── Explainability event tracker (ISSUE-10 layers 1-3) ─────────────
        from src.inference.detection_tracker import DetectionTracker
        self._tracker = DetectionTracker(bed_id)

        # ── Thread safety (BUG-5) ─────────────────────────────────────────
        self._state_lock = threading.Lock()

        # ── God Mode integration (§10.6) ──────────────────────────────────
        # Default: zero overhead. Injector only created when god_mode=True.
        # The src/god_mode module is implemented in Phase 4.
        # If not yet available, god_mode is silently disabled.
        self._god_mode = god_mode
        self._injector = None
        if god_mode:
            try:
                from src.god_mode.injector import GodModeInjector  # type: ignore[import]  # Phase 4
                self._injector = GodModeInjector.get()
            except ImportError:
                logger.warning(
                    f"[{bed_id}] god_mode=True but src/god_mode not available "
                    "(Phase 4 not yet implemented). God Mode disabled."
                )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def on_new_sample(self, fhr_norm: float, uc_norm: float) -> "BedState | None":
        """Push one normalized sample at 4 Hz.

        Args:
            fhr_norm: FHR normalized [0, 1]  — i.e. (bpm - 50) / 160
            uc_norm:  UC normalized  [0, 1]  — i.e. mmHg / 100

        Returns:
            BedState every 24 calls once ring has >= 1800 samples.
            None during warmup or on non-inference ticks.

        Thread safety: called from ThreadPoolExecutor workers (BUG-8 fix at
        PipelineManager level). The lock is held for the full duration of the
        call, including any PatchTST inference — callers must not hold locks
        that this method might need.
        """
        with self._state_lock:
            self._fhr_ring.append(fhr_norm)
            self._uc_ring.append(uc_norm)
            self._sample_count += 1

            if ((self._sample_count - self._inference_offset) % _INFERENCE_STRIDE == 0
                    and len(self._fhr_ring) >= _WINDOW_LEN):
                # Convert deque → numpy ONCE; reuse in _compute_full_state
                fhr_full = np.array(self._fhr_ring, dtype=np.float32)
                uc_full = np.array(self._uc_ring, dtype=np.float32)
                fhr_win = fhr_full[-_WINDOW_LEN:]
                uc_win = uc_full[-_WINDOW_LEN:]
                signal = np.stack([fhr_win, uc_win])

                prob = self._run_ensemble(signal)
                # BUG-6 contract: on inference failure skip this tick entirely.
                if prob is None:
                    return None

                start = max(0, self._sample_count - _WINDOW_LEN)
                self._window_scores.append((start, prob))
                # Cap to prevent unbounded growth
                if len(self._window_scores) > _WINDOW_SCORE_MAX:
                    self._window_scores = self._window_scores[-_WINDOW_SCORE_MAX:]
                return self._compute_full_state(fhr_full, uc_full)

        return None

    def reset(self) -> None:
        """Clear all buffers and reset sample counter.

        Called when a recording loops back to the start.
        Thread-safe: acquires _state_lock, blocks until any in-progress
        inference completes.
        """
        with self._state_lock:
            self._fhr_ring.clear()
            self._uc_ring.clear()
            self._window_scores.clear()
            self._risk_history.clear()
            self._sample_count = 0
            self._tracker.reset()

    @property
    def bed_id(self) -> str:
        """Public accessor for the bed identifier."""
        return self._bed_id

    @property
    def current_sample_count(self) -> int:
        """Total samples pushed so far. Used by God Mode for timestamp anchoring.

        BUG-3: must be a @property, not a plain attribute access.
        """
        return self._sample_count

    # ------------------------------------------------------------------
    # Internal helpers — called while _state_lock is held
    # ------------------------------------------------------------------

    def _run_ensemble(self, signal: np.ndarray) -> float | None:
        """Run 5-fold PatchTST ensemble on a 1800-sample window.

        Args:
            signal: shape (2, 1800) — already normalized (FHR∈[0,1], UC∈[0,1]).
                    Direct slice from ring buffer; NO re-normalization needed.

        Returns:
            Mean P(acidemia) across 5 folds in [0, 1], or None on failure.

        Thread safety: models are read-only (eval mode) — multiple beds may
        call this concurrently from the ThreadPoolExecutor.

        BUG-6: Any exception is caught and logged; None is returned so the
        calling tick is skipped rather than crashing the bed's pipeline.
        """
        try:
            import torch
            # Shape: (1, 2, 1800)
            x = torch.tensor(signal, dtype=torch.float32).unsqueeze(0)
            with torch.no_grad():
                probs = [
                    torch.softmax(m(x), dim=-1)[0, 1].item()
                    for m in self._models
                ]
            return float(np.mean(probs))
        except Exception as exc:
            logger.error(f"[{self._bed_id}] PatchTST ensemble failed: {exc}")
            return None

    def _compute_full_state(self, fhr_arr: np.ndarray, uc_arr: np.ndarray) -> BedState:
        """Assemble 25-feature LR vector and return a BedState.

        Called from on_new_sample() while _state_lock is held.
        Every 24 samples after warmup.

        Args:
            fhr_arr: pre-converted numpy array from ring buffer (avoids redundant conversion)
            uc_arr:  pre-converted numpy array from ring buffer

        Feature vector order (must match production_config.json feature_names):
            [0–11]  12 AI features    (extract_recording_features)
            [12–22] 11 clinical       (extract_clinical_features)
            [23–24] 2  global         (overall_mean_prob, overall_std_prob)
        """
        from src.features.clinical_extractor import (
            CLINICAL_FEATURE_NAMES,
            extract_clinical_features_with_intervals,
        )
        from src.inference.alert_extractor import extract_recording_features
        from src.inference.explainability import compute_top_contributions

        # _window_scores already includes the current tick score from on_new_sample().
        # BUG-6: this function is called only when current inference succeeded.

        # ── 12 AI features ────────────────────────────────────────────────
        # Use config["best_at"] = 0.5 — the threshold the LR was trained with.
        # NOT the hardcoded ALERT_THRESHOLD=0.4 in alert_extractor.py (dev only).
        at = self._config.get("best_at", _DEFAULT_BEST_AT)
        pt_feats = extract_recording_features(
            self._window_scores,
            threshold=at,
            inference_stride=_INFERENCE_STRIDE,
            n_features=12,
        )

        # ── 11 clinical features ──────────────────────────────────────────
        # extract_clinical_features expects normalized (2, T) — ring is already normalized.
        # Internally it denormalizes: FHR = sig*160+50, UC = sig*100 for rule-based logic.
        full_signal = np.stack([fhr_arr, uc_arr])              # (2, T) normalized
        sample_offset = max(0, self._sample_count - len(fhr_arr))
        clinical_result = extract_clinical_features_with_intervals(
            full_signal,
            sample_offset=sample_offset,
        )
        clin_list = clinical_result["features"]                # List[float], len=11
        clinical_intervals = clinical_result["intervals"]      # absolute sample intervals

        # ── 2 global features ─────────────────────────────────────────────
        all_probs = [p for _, p in self._window_scores]
        global_feat = [float(np.mean(all_probs)), float(np.std(all_probs))]

        # ── God Mode override (§10.6) ─────────────────────────────────────
        # O(1) fast check on non-God-Mode beds (self._injector is None → skip).
        god_mode_active = False
        active_events: list = []

        if (self._injector is not None
                and self._injector.has_active_events(self._bed_id, self._sample_count)):
            god_mode_active = True
            clin_list, window_scores_adj, active_events = self._injector.compute_override(
                bed_id=self._bed_id,
                current_sample=self._sample_count,
                clin_list=clin_list,
                window_scores=self._window_scores,
                elapsed_seconds=self._sample_count / 4.0,
            )
            # Recompute global and PT features from adjusted window scores
            adj_probs = [p for _, p in window_scores_adj]
            global_feat = [float(np.mean(adj_probs)), float(np.std(adj_probs))]
            pt_feats = extract_recording_features(
                window_scores_adj, threshold=at,
                inference_stride=_INFERENCE_STRIDE, n_features=12,
            )

        # ── Assemble 25-feature vector ─────────────────────────────────────
        # Order: 12 PT → 11 clinical → 2 global (matches production_config feature_names)
        x = np.array(
            list(pt_feats.values()) + clin_list + global_feat,
            dtype=np.float64,
        ).reshape(1, -1)   # (1, 25)

        # ── LR prediction ─────────────────────────────────────────────────
        x_scaled = self._scaler.transform(x)
        risk = float(self._lr.predict_proba(x_scaled)[0, 1])
        if np.isfinite(risk):
            top_contributions = compute_top_contributions(
                x_raw=x[0],
                x_scaled=x_scaled[0],
                lr=self._lr,
                feature_names=self._feature_names,
                top_k=5,
            )
        else:
            top_contributions = []

        # ── Risk trend delta (§11.15) ──────────────────────────────────────
        self._risk_history.append(risk)
        if len(self._risk_history) > 10:
            self._risk_history = self._risk_history[-10:]
        risk_delta = 0.0
        if len(self._risk_history) >= 4:
            risk_delta = round(risk - self._risk_history[-4], 4)

        # ── Threshold ────────────────────────────────────────────────────
        decision_threshold = self._config.get(
            "decision_threshold", _DEFAULT_DECISION_THRESHOLD
        )

        # ── Display values — denormalize for UI (BUG-7: exactly 24 = 1 stride) ──
        # Sending last 24 per tick guarantees no gaps in the frontend CTG chart.
        fhr_display = [round(float(v) * 160.0 + 50.0, 1) for v in fhr_arr[-24:]]
        uc_display = [round(float(v) * 100.0, 1) for v in uc_arr[-24:]]

        # ── Clinical dict for named field assignment ─────────────────────
        clin_dict = dict(zip(CLINICAL_FEATURE_NAMES, clin_list))

        state = BedState(
            bed_id=self._bed_id,
            recording_id=self._recording_id,
            timestamp=time.time(),
            risk_score=risk,
            alert=risk > decision_threshold,
            alert_threshold=decision_threshold,
            window_prob=all_probs[-1] if all_probs else 0.0,
            fhr_latest=fhr_display,
            uc_latest=uc_display,
            # Clinical fields — exact CLINICAL_FEATURE_NAMES order:
            baseline_bpm=float(clin_dict["baseline_bpm"]),
            is_tachycardia=float(clin_dict["is_tachycardia"]),
            is_bradycardia=float(clin_dict["is_bradycardia"]),
            variability_amplitude_bpm=float(clin_dict["variability_amplitude_bpm"]),
            variability_category=float(clin_dict["variability_category"]),
            n_late_decelerations=int(clin_dict["n_late_decelerations"]),
            n_variable_decelerations=int(clin_dict["n_variable_decelerations"]),
            n_prolonged_decelerations=int(clin_dict["n_prolonged_decelerations"]),
            max_deceleration_depth_bpm=float(clin_dict["max_deceleration_depth_bpm"]),
            sinusoidal_detected=bool(clin_dict["sinusoidal_detected"]),
            tachysystole_detected=bool(clin_dict["tachysystole_detected"]),
            elapsed_seconds=self._sample_count / 4.0,
            warmup=len(self._fhr_ring) < _WINDOW_LEN,
            sample_count=self._sample_count,
            risk_delta=risk_delta,
            last_update_server_ts=time.time(),
            god_mode_active=god_mode_active,
            active_events=active_events,
            top_contributions=top_contributions,
        )

        self._tracker.update(
            state,
            x_raw=x[0],
            top_contributions=top_contributions,
            clinical_intervals=clinical_intervals,
        )
        state.detection_events = self._tracker.flush_pending()
        return state


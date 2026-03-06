"""
api/main.py — FastAPI application entry point.

Lifespan order (AGENTS.md Phase 3 / PLAN.md §4):
  1. setup_logging()
  2. validate production_config.json
  3. load_production_models()
  4. broadcaster = AsyncBroadcaster()
  5. manager = PipelineManager(broadcaster, ...)   ← broadcaster FIRST (BUG-2)
  6. engine = ReplayEngine(..., callback=manager.on_sample)
  7. check recordings_dir ≥ 1 .npy — RuntimeError if missing
  8. asyncio.create_task(engine.run())
  9. asyncio.create_task(broadcaster.run())
 10. manager.set_beds(default_beds, engine)
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.config import settings
from api.logging_config import setup_logging

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Step 1: Logging ───────────────────────────────────────────────────
    setup_logging(settings.log_dir)
    logger.info("SentinelFetal2 starting up …")

    # ── Step 2: Validate config ───────────────────────────────────────────
    prod_cfg_path = settings.artifacts_dir / "production_config.json"
    if not prod_cfg_path.exists():
        raise RuntimeError(f"production_config.json not found at {prod_cfg_path}")

    # ── Step 3: Load models (blocking — must complete before loop starts) ─
    from api.services.model_loader import load_production_models

    models, scaler, lr_model, prod_cfg = load_production_models()
    logger.info(
        "Models loaded: %d folds, threshold=%.4f",
        len(models),
        prod_cfg.get("decision_threshold", 0.0),
    )

    # ── Step 4: AsyncBroadcaster ──────────────────────────────────────────
    from api.services.broadcaster import AsyncBroadcaster

    broadcaster = AsyncBroadcaster()

    # ── Step 5: PipelineManager — broadcaster first (BUG-2) ───────────────
    from api.services.pipeline_manager import PipelineManager

    manager = PipelineManager(
        broadcaster=broadcaster,
        models=models,
        scaler=scaler,
        lr_model=lr_model,
        config=prod_cfg,
        recordings_dir=Path(settings.recordings_dir),
    )

    # ── Step 6: ReplayEngine ──────────────────────────────────────────────
    from generator.replay import ReplayEngine

    engine = ReplayEngine(
        beds={},
        recordings_dir=Path(settings.recordings_dir),
        callback=manager.on_sample,
    )

    # ── Step 7: Fail-fast if recordings are missing ───────────────────────
    recordings_dir = Path(settings.recordings_dir)
    if not recordings_dir.exists() or not any(recordings_dir.glob("*.npy")):
        raise RuntimeError(
            f"No .npy recordings found in {recordings_dir}. "
            "Is the data directory present?"
        )

    # ── Steps 8–9: Start background tasks ─────────────────────────────────
    engine_task = asyncio.create_task(engine.run(), name="replay-engine")
    broadcaster_task = asyncio.create_task(broadcaster.run(), name="broadcaster")

    # ── Step 10: Default beds ─────────────────────────────────────────────
    default_beds = [
        {"bed_id": f"bed_{i + 1:02d}", "recording_id": None}
        for i in range(settings.default_bed_count)
    ]
    manager.set_beds(default_beds, engine)
    logger.info("Default beds configured: %s", [b["bed_id"] for b in default_beds])

    # ── Expose singletons on app.state ────────────────────────────────────
    app.state.manager = manager
    app.state.engine = engine
    app.state.broadcaster = broadcaster
    # Store the running loop so sync handlers can reschedule engine.run() after stop.
    app.state.loop = asyncio.get_running_loop()

    logger.info("SentinelFetal2 startup complete. beds=%d", settings.default_bed_count)

    yield   # ── Application runs ──────────────────────────────────────────

    # ── Shutdown ──────────────────────────────────────────────────────────
    logger.info("SentinelFetal2 shutting down …")
    engine.stop()
    engine_task.cancel()
    broadcaster_task.cancel()
    try:
        await asyncio.gather(engine_task, broadcaster_task, return_exceptions=True)
    except Exception:
        pass
    logger.info("SentinelFetal2 shutdown complete.")


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------

def create_app() -> FastAPI:
    app = FastAPI(
        title="SentinelFetal2",
        description="Real-time fetal monitoring system — FastAPI backend",
        version="2.0.0",
        lifespan=lifespan,
    )

    # CORS — dev mode (Vite on :5173, CRA on :3000).
    # In production, same-origin nginx proxy is used — CORS not needed.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── God Mode middleware — PIN auth for /api/god-mode/* ──────────────────
    from api.middleware.god_mode_guard import GodModeGuard
    app.add_middleware(GodModeGuard, pin=settings.god_mode_pin)

    # ── Routers ────────────────────────────────────────────────────────────
    from api.routers import beds, god_mode, recordings, simulation, system, websocket

    app.include_router(simulation.router)
    app.include_router(beds.router)
    app.include_router(websocket.router)
    app.include_router(recordings.router)
    app.include_router(system.router)
    app.include_router(god_mode.router)

    # ── Health endpoint ────────────────────────────────────────────────────
    from api.models.schemas import HealthResponse

    @app.get("/api/health", response_model=HealthResponse, tags=["health"])
    def health() -> HealthResponse:
        try:
            manager = app.state.manager
            active = len(manager.active_bed_ids())
            models_loaded = True
        except AttributeError:
            active = 0
            models_loaded = False

        recordings_dir = Path(settings.recordings_dir)
        recording_count = len(list(recordings_dir.glob("*.npy"))) if recordings_dir.exists() else 0

        return HealthResponse(
            status="ok",
            models_loaded=models_loaded,
            active_beds=active,
            recording_count=recording_count,
        )

    return app


# Module-level app instance — used by uvicorn
app = create_app()

"""
api/routers/simulation.py — Simulation control endpoints.

Endpoints:
  GET  /api/simulation/status   — current simulation state
  POST /api/simulation/start    — start / reconfigure beds
  POST /api/simulation/stop     — stop simulation
  POST /api/simulation/pause    — pause tick loop
  POST /api/simulation/resume   — resume tick loop
  POST /api/simulation/speed    — change replay speed [1–20]
"""
from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException, Request

from api.dependencies import get_engine, get_manager
from api.models.schemas import (
    SimulationStatus,
    SpeedRequest,
    StartSimulationRequest,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/simulation", tags=["simulation"])


def _sim_status(engine, manager) -> SimulationStatus:
    return SimulationStatus(
        running=engine._running,
        paused=engine._paused,
        bed_count=len(manager.active_bed_ids()),
        speed=engine._speed,
        active_bed_ids=manager.active_bed_ids(),
        tick_count=engine._tick_count,
        elapsed_seconds=engine._tick_count * 0.25,
    )


@router.get("/status", response_model=SimulationStatus)
def get_status(
    request: Request,
    engine=Depends(get_engine),
    manager=Depends(get_manager),
) -> SimulationStatus:
    return _sim_status(engine, manager)


@router.post("/start", response_model=SimulationStatus)
def start_simulation(
    request: Request,
    body: StartSimulationRequest | None = None,
    engine=Depends(get_engine),
    manager=Depends(get_manager),
) -> SimulationStatus:
    """
    Start the simulation, optionally with a new bed configuration.
    If beds is None, keeps the existing configuration.
    """
    if body and body.beds:
        configs = [{"bed_id": b.bed_id, "recording_id": b.recording_id} for b in body.beds]
        if len(configs) > 16:
            raise HTTPException(status_code=422, detail="Max 16 beds allowed")
        manager.set_beds(configs, engine)

    if not engine._running:
        # Engine was hard-stopped: engine.run() exited and resume() is a no-op.
        # Schedule a fresh run() coroutine on the event loop from this sync handler.
        loop: asyncio.AbstractEventLoop = request.app.state.loop
        asyncio.run_coroutine_threadsafe(engine.run(), loop)
        # Optimistic flag so _sim_status() reflects intent immediately;
        # engine.run() will also set _running=True once it starts executing.
        engine._running = True
    elif engine._paused:
        engine.resume()

    logger.info("Simulation started/resumed. beds=%s", manager.active_bed_ids())
    audit_logger = logging.getLogger("sentinel.audit")
    audit_logger.info("SIMULATION_START | beds=%s", manager.active_bed_ids())

    return _sim_status(engine, manager)


@router.post("/stop", response_model=SimulationStatus)
def stop_simulation(engine=Depends(get_engine), manager=Depends(get_manager)) -> SimulationStatus:
    engine.stop()   # hard stop — exits the tick loop permanently
    audit_logger = logging.getLogger("sentinel.audit")
    audit_logger.info("SIMULATION_STOP")
    return _sim_status(engine, manager)


@router.post("/pause", response_model=SimulationStatus)
def pause_simulation(engine=Depends(get_engine), manager=Depends(get_manager)) -> SimulationStatus:
    engine.pause()
    return _sim_status(engine, manager)


@router.post("/resume", response_model=SimulationStatus)
def resume_simulation(engine=Depends(get_engine), manager=Depends(get_manager)) -> SimulationStatus:
    engine.resume()
    return _sim_status(engine, manager)


@router.post("/speed", response_model=SimulationStatus)
def set_speed(
    body: SpeedRequest,
    engine=Depends(get_engine),
    manager=Depends(get_manager),
) -> SimulationStatus:
    engine.set_speed(body.speed)
    logger.info("Speed set to %.1f×", body.speed)
    return _sim_status(engine, manager)

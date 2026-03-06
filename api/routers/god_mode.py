"""
api/routers/god_mode.py — God Mode endpoints
=============================================

Endpoints:
  POST   /api/god-mode/inject              — inject an event (feature override + signal swap)
  DELETE /api/god-mode/events/{event_id}   — end an ongoing event
  GET    /api/god-mode/events              — list events for a bed
  DELETE /api/god-mode/clear/{bed_id}      — clear all events for a bed
  POST   /api/god-mode/enable              — enable God Mode system-wide
  GET    /api/god-mode/status              — check God Mode status

All endpoints require X-God-Mode-Pin header (enforced by GodModeGuard middleware).

PLAN.md references: §10.8, docs/god_mode_signal_plan.md
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from api.dependencies import get_engine, get_manager
from src.god_mode.injector import GodModeInjector
from src.god_mode.types import EventType, InjectionEvent

logger = logging.getLogger(__name__)
audit_logger = logging.getLogger("sentinel.audit")

router = APIRouter(prefix="/api/god-mode", tags=["god-mode"])


# ── Request / Response models ──────────────────────────────────────────────


class InjectRequest(BaseModel):
    bed_id: str
    event_type: EventType
    severity: float = Field(default=0.85, ge=0.5, le=1.0)
    duration_seconds: float | None = None   # None = ongoing until manual stop
    description: str = ""


class InjectResponse(BaseModel):
    event_id: str
    status: str
    signal_swapped: bool
    start_sample: int


class EventResponse(BaseModel):
    event_id: str
    bed_id: str
    event_type: str
    start_sample: int
    end_sample: int | None
    severity: float
    description: str
    signal_swapped: bool
    original_recording_id: str | None


class EndEventResponse(BaseModel):
    status: str
    recording_restored: bool


# ── Endpoints ──────────────────────────────────────────────────────────────


@router.post("/inject", response_model=InjectResponse)
async def inject_event(
    req: InjectRequest,
    manager=Depends(get_manager),
    engine=Depends(get_engine),
):
    """Inject a God Mode event: feature override + optional signal swap."""
    pipeline = manager.get_pipeline(req.bed_id)
    if pipeline is None:
        raise HTTPException(404, f"Bed '{req.bed_id}' not found")

    # Ensure God Mode is enabled system-wide
    if not manager.god_mode_enabled:
        manager.enable_god_mode()

    current_sample = pipeline.current_sample_count

    # Duration → sample count
    duration_samples = None
    if req.duration_seconds is not None:
        duration_samples = int(req.duration_seconds * 4)  # 4 Hz

    # Create injection event
    event = InjectionEvent.create(
        bed_id=req.bed_id,
        event_type=req.event_type,
        start_sample=current_sample,
        duration_samples=duration_samples,
        severity=req.severity,
        description=req.description,
    )

    # Signal swap — try to find a real recording with this pathology
    segment_store = getattr(manager, "_segment_store", None)
    if segment_store is not None:
        segment = segment_store.get_segment(req.event_type.value)
        if segment is not None:
            old_id = engine.swap_recording(
                req.bed_id,
                segment["recording_id"],
                segment.get("best_start_sample", 0),
            )
            event.original_recording_id = old_id
            event.signal_swapped = True

    # Register feature override (immediate effect on risk score)
    GodModeInjector.get().add_event(event)

    audit_logger.info(
        "GOD_MODE_INJECT | bed=%s type=%s severity=%.2f signal_swapped=%s event_id=%s",
        req.bed_id, req.event_type.value, req.severity,
        event.signal_swapped, event.event_id,
    )

    return InjectResponse(
        event_id=event.event_id,
        status="injected",
        signal_swapped=event.signal_swapped,
        start_sample=current_sample,
    )


@router.delete("/events/{event_id}", response_model=EndEventResponse)
async def end_event(
    event_id: str,
    bed_id: str = Query(..., description="Bed ID"),
    manager=Depends(get_manager),
    engine=Depends(get_engine),
):
    """End an ongoing God Mode event. Restores original recording if swapped."""
    pipeline = manager.get_pipeline(bed_id)
    if pipeline is None:
        raise HTTPException(404, f"Bed '{bed_id}' not found")

    injector = GodModeInjector.get()
    current_sample = pipeline.current_sample_count

    # Get event before ending (to access original_recording_id)
    event = injector.get_event(bed_id, event_id)
    recording_restored = False

    if event and event.original_recording_id:
        engine.swap_recording(bed_id, event.original_recording_id, 0)
        recording_restored = True

    ok = injector.end_event(bed_id, event_id, current_sample)

    audit_logger.info(
        "GOD_MODE_END | bed=%s event_id=%s recording_restored=%s",
        bed_id, event_id, recording_restored,
    )

    return EndEventResponse(
        status="ended" if ok else "not_found",
        recording_restored=recording_restored,
    )


@router.get("/events", response_model=list[EventResponse])
async def list_events(
    bed_id: str = Query(..., description="Bed ID"),
):
    """List all events for a bed."""
    events = GodModeInjector.get().get_events(bed_id)
    return [
        EventResponse(
            event_id=e.event_id,
            bed_id=e.bed_id,
            event_type=e.event_type.value,
            start_sample=e.start_sample,
            end_sample=e.end_sample,
            severity=e.severity,
            description=e.description,
            signal_swapped=e.signal_swapped,
            original_recording_id=e.original_recording_id,
        )
        for e in events
    ]


@router.delete("/clear/{bed_id}")
async def clear_bed(
    bed_id: str,
    engine=Depends(get_engine),
):
    """Clear all events for a bed. Restores original recording if any were swapped."""
    removed = GodModeInjector.get().clear_bed(bed_id)

    # Restore original recording from the most recent swapped event
    for event in reversed(removed):
        if event.original_recording_id:
            engine.swap_recording(bed_id, event.original_recording_id, 0)
            break

    audit_logger.info("GOD_MODE_CLEAR | bed=%s removed=%d", bed_id, len(removed))
    return {"status": "cleared", "removed_count": len(removed)}


@router.post("/enable")
async def enable_god_mode(
    manager=Depends(get_manager),
):
    """Enable God Mode system-wide."""
    manager.enable_god_mode()
    return {"status": "enabled"}


@router.get("/status")
async def god_mode_status(
    manager=Depends(get_manager),
):
    """Check current God Mode status."""
    segment_store = getattr(manager, "_segment_store", None)
    available_types = segment_store.available_types() if segment_store else []

    return {
        "enabled": manager.god_mode_enabled,
        "signal_swap_available": segment_store is not None,
        "available_event_types": available_types,
    }

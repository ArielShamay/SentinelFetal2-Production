"""
api/routers/beds.py — Bed-level REST endpoints.

Endpoints:
  GET  /api/beds                        — list all active beds + latest BedState
  GET  /api/beds/{bed_id}               — single bed snapshot
  GET  /api/beds/{bed_id}/history       — FHR/UC ring buffer data (last N minutes)
  GET  /api/beds/{bed_id}/alerts        — alert transition history
  GET  /api/beds/{bed_id}/notes         — clinical notes
  POST /api/beds/{bed_id}/notes         — add a clinical note
  GET  /api/beds/{bed_id}/export        — export risk + clinical timeline (CSV/JSON)
  POST /api/beds/config                 — update active bed configuration
"""
from __future__ import annotations

import dataclasses
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from api.dependencies import get_manager
from api.models.schemas import (
    AlertEventSchema,
    AlertHistoryResponse,
    BedConfigItem,
    BedExportResponse,
    BedExportRow,
    BedListResponse,
    BedNoteSchema,
    BedSnapshot,
    NoteListResponse,
    NoteRequest,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/beds", tags=["beds"])


def _state_to_snapshot(state) -> BedSnapshot:
    """Convert BedState dataclass to BedSnapshot Pydantic model."""
    d = dataclasses.asdict(state)
    return BedSnapshot(**{k: v for k, v in d.items() if k in BedSnapshot.model_fields})


# ---------------------------------------------------------------------------
# GET /api/beds
# ---------------------------------------------------------------------------

@router.get("", response_model=BedListResponse)
def list_beds(manager=Depends(get_manager)) -> BedListResponse:
    states = manager.get_bed_states()
    snapshots = [_state_to_snapshot(s) for s in states]
    # Sort highest risk first
    snapshots.sort(key=lambda s: s.risk_score, reverse=True)
    return BedListResponse(beds=snapshots, total=len(snapshots))


# ---------------------------------------------------------------------------
# POST /api/beds/config — must be declared before /{bed_id}
# ---------------------------------------------------------------------------

@router.post("/config", response_model=BedListResponse)
def configure_beds(
    request: Request,
    body: list[BedConfigItem],
    manager=Depends(get_manager),
) -> BedListResponse:
    """
    Atomically replace the active bed configuration.
    Accepts a list of {bed_id, recording_id} items (recording_id may be null for random).
    Maximum 16 beds.
    """
    from api.dependencies import get_engine

    if len(body) > 16:
        raise HTTPException(status_code=422, detail="Max 16 beds allowed")

    engine = get_engine(request)
    configs = [{"bed_id": b.bed_id, "recording_id": b.recording_id} for b in body]
    try:
        manager.set_beds(configs, engine)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    states = manager.get_bed_states()
    snapshots = [_state_to_snapshot(s) for s in states]
    snapshots.sort(key=lambda s: s.risk_score, reverse=True)
    return BedListResponse(beds=snapshots, total=len(snapshots))


# ---------------------------------------------------------------------------
# GET /api/beds/{bed_id}
# ---------------------------------------------------------------------------

@router.get("/{bed_id}", response_model=BedSnapshot)
def get_bed(bed_id: str, manager=Depends(get_manager)) -> BedSnapshot:
    state = manager.get_last_state(bed_id)
    if state is None:
        raise HTTPException(status_code=404, detail=f"Bed '{bed_id}' not found or no data yet")
    return _state_to_snapshot(state)


# ---------------------------------------------------------------------------
# GET /api/beds/{bed_id}/history
# ---------------------------------------------------------------------------

@router.get("/{bed_id}/history")
def get_bed_history(bed_id: str, manager=Depends(get_manager)) -> dict:
    """
    Returns the pipeline's ring buffer contents for FHR/UC (denormalized).
    Up to 30 minutes of data (7200 samples per channel at 4 Hz).
    """
    pipeline = manager.get_pipeline(bed_id)
    if pipeline is None:
        raise HTTPException(status_code=404, detail=f"Bed '{bed_id}' not found")

    import numpy as np
    fhr_ring = list(pipeline._fhr_ring)
    uc_ring = list(pipeline._uc_ring)

    # Denormalize for display
    fhr_bpm = [round(v * 160.0 + 50.0, 1) for v in fhr_ring]
    uc_mmhg = [round(v * 100.0, 1) for v in uc_ring]

    sample_count = len(fhr_ring)
    duration_s = sample_count / 4.0  # 4 Hz

    return {
        "bed_id": bed_id,
        "sample_count": sample_count,
        "duration_seconds": duration_s,
        "fhr_bpm": fhr_bpm,
        "uc_mmhg": uc_mmhg,
    }


# ---------------------------------------------------------------------------
# GET /api/beds/{bed_id}/alerts
# ---------------------------------------------------------------------------

@router.get("/{bed_id}/alerts", response_model=AlertHistoryResponse)
def get_bed_alerts(
    bed_id: str,
    last_n: int = 50,
    manager=Depends(get_manager),
) -> AlertHistoryResponse:
    events = manager.alert_history.get_history(bed_id, last_n=last_n)
    schema_events = [
        AlertEventSchema(
            bed_id=e.bed_id,
            timestamp=e.timestamp,
            risk_score=e.risk_score,
            alert_on=e.alert_on,
            elapsed_s=e.elapsed_s,
        )
        for e in events
    ]
    return AlertHistoryResponse(bed_id=bed_id, events=schema_events)


# ---------------------------------------------------------------------------
# GET/POST /api/beds/{bed_id}/notes
# ---------------------------------------------------------------------------

@router.get("/{bed_id}/notes", response_model=NoteListResponse)
def get_notes(
    bed_id: str,
    last_n: int = 50,
    manager=Depends(get_manager),
) -> NoteListResponse:
    notes = manager.note_store.get(bed_id, last_n=last_n)
    schema_notes = [
        BedNoteSchema(
            note_id=n.note_id,
            bed_id=n.bed_id,
            text=n.text,
            created_at=n.created_at,
        )
        for n in notes
    ]
    return NoteListResponse(bed_id=bed_id, notes=schema_notes)


@router.post("/{bed_id}/notes", response_model=BedNoteSchema, status_code=201)
def add_note(
    bed_id: str,
    body: NoteRequest,
    manager=Depends(get_manager),
) -> BedNoteSchema:
    # Verify bed exists
    if manager.get_pipeline(bed_id) is None:
        raise HTTPException(status_code=404, detail=f"Bed '{bed_id}' not found")

    from api.services.note_store import BedNote
    note = BedNote(bed_id=bed_id, text=body.text)
    saved = manager.note_store.add(note)
    return BedNoteSchema(
        note_id=saved.note_id,
        bed_id=saved.bed_id,
        text=saved.text,
        created_at=saved.created_at,
    )


# ---------------------------------------------------------------------------
# GET /api/beds/{bed_id}/export
# ---------------------------------------------------------------------------

@router.get("/{bed_id}/export", response_model=BedExportResponse)
def export_bed_data(bed_id: str, manager=Depends(get_manager)) -> BedExportResponse:
    """
    Export time-series risk score + key clinical fields for a bed.
    Returns JSON; client may choose to serialize to CSV.
    """
    state = manager.get_last_state(bed_id)
    if state is None:
        raise HTTPException(status_code=404, detail=f"Bed '{bed_id}' not found or no data yet")

    # Build export from alert history (all recorded BedStates at transition pts)
    alert_events = manager.alert_history.get_history(bed_id, last_n=200)

    rows = [
        BedExportRow(
            timestamp=e.timestamp,
            risk_score=e.risk_score,
            alert=e.alert_on,
            baseline_bpm=state.baseline_bpm,
            n_late_decelerations=state.n_late_decelerations,
            n_variable_decelerations=state.n_variable_decelerations,
            n_prolonged_decelerations=state.n_prolonged_decelerations,
        )
        for e in alert_events
    ]

    return BedExportResponse(
        bed_id=bed_id,
        recording_id=state.recording_id,
        rows=rows,
    )

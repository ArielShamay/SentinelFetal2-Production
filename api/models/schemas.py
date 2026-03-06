"""
api/models/schemas.py — Pydantic v2 request/response schemas.

Mirrors BedState from src/inference/pipeline.py.
All field names and types are kept in sync with BedState dataclass.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# WebSocket message schemas
# ---------------------------------------------------------------------------

class BedUpdate(BaseModel):
    """Single-bed update — transmitted inside batch_update.updates list."""

    bed_id: str
    recording_id: str
    risk_score: float = Field(ge=0.0, le=1.0)
    alert: bool
    alert_threshold: float
    window_prob: float

    # Display values (denormalized by backend)
    fhr_latest: list[float]   # last 24 FHR values in BPM
    uc_latest: list[float]    # last 24 UC values in mmHg

    # Clinical features — exact CLINICAL_FEATURE_NAMES order
    baseline_bpm: float
    is_tachycardia: float
    is_bradycardia: float
    variability_amplitude_bpm: float
    variability_category: float
    n_late_decelerations: int
    n_variable_decelerations: int
    n_prolonged_decelerations: int
    max_deceleration_depth_bpm: float
    sinusoidal_detected: bool
    tachysystole_detected: bool

    elapsed_seconds: float
    warmup: bool
    sample_count: int

    # Optional God Mode fields
    god_mode_active: bool = False
    active_events: list = Field(default_factory=list)
    risk_delta: float = 0.0
    last_update_server_ts: float = 0.0


class BatchUpdateMessage(BaseModel):
    type: Literal["batch_update"] = "batch_update"
    timestamp: float
    updates: list[BedUpdate]


class InitialStateMessage(BaseModel):
    type: Literal["initial_state"] = "initial_state"
    beds: list[BedUpdate]


class HeartbeatMessage(BaseModel):
    type: Literal["heartbeat"] = "heartbeat"
    ts: float


# ---------------------------------------------------------------------------
# Simulation schemas
# ---------------------------------------------------------------------------

class BedConfigItem(BaseModel):
    bed_id: str
    recording_id: str | None = None


class StartSimulationRequest(BaseModel):
    beds: list[BedConfigItem] | None = None


class SpeedRequest(BaseModel):
    speed: float = Field(ge=1.0, le=20.0)


class SimulationStatus(BaseModel):
    running: bool
    paused: bool
    bed_count: int
    speed: float
    active_bed_ids: list[str]
    tick_count: int = 0
    elapsed_seconds: float = 0.0


# ---------------------------------------------------------------------------
# Bed schemas
# ---------------------------------------------------------------------------

class BedSnapshot(BaseModel):
    """Full snapshot of a single bed — same fields as BedUpdate."""

    bed_id: str
    recording_id: str
    risk_score: float
    alert: bool
    alert_threshold: float
    window_prob: float
    fhr_latest: list[float]
    uc_latest: list[float]
    baseline_bpm: float
    is_tachycardia: float
    is_bradycardia: float
    variability_amplitude_bpm: float
    variability_category: float
    n_late_decelerations: int
    n_variable_decelerations: int
    n_prolonged_decelerations: int
    max_deceleration_depth_bpm: float
    sinusoidal_detected: bool
    tachysystole_detected: bool
    elapsed_seconds: float
    warmup: bool
    sample_count: int
    god_mode_active: bool = False
    active_events: list = Field(default_factory=list)
    risk_delta: float = 0.0


class BedListResponse(BaseModel):
    beds: list[BedSnapshot]
    total: int


# ---------------------------------------------------------------------------
# Alert history schemas
# ---------------------------------------------------------------------------

class AlertEventSchema(BaseModel):
    bed_id: str
    timestamp: float
    risk_score: float
    alert_on: bool
    elapsed_s: float


class AlertHistoryResponse(BaseModel):
    bed_id: str
    events: list[AlertEventSchema]


# ---------------------------------------------------------------------------
# Notes schemas
# ---------------------------------------------------------------------------

class NoteRequest(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


class BedNoteSchema(BaseModel):
    note_id: str
    bed_id: str
    text: str
    created_at: float


class NoteListResponse(BaseModel):
    bed_id: str
    notes: list[BedNoteSchema]


# ---------------------------------------------------------------------------
# Recording schemas
# ---------------------------------------------------------------------------

class RecordingInfo(BaseModel):
    recording_id: str
    duration_seconds: float
    file_size_kb: int


class RecordingListResponse(BaseModel):
    recordings: list[RecordingInfo]
    total: int


# ---------------------------------------------------------------------------
# System / health schemas
# ---------------------------------------------------------------------------

class HealthResponse(BaseModel):
    status: str
    models_loaded: bool
    active_beds: int
    recording_count: int


class StartupStatusEvent(BaseModel):
    step: str
    status: Literal["ok", "error", "pending"]
    detail: str = ""


# ---------------------------------------------------------------------------
# Export schema
# ---------------------------------------------------------------------------

class BedExportRow(BaseModel):
    timestamp: float
    risk_score: float
    alert: bool
    baseline_bpm: float
    n_late_decelerations: int
    n_variable_decelerations: int
    n_prolonged_decelerations: int


class BedExportResponse(BaseModel):
    bed_id: str
    recording_id: str
    rows: list[BedExportRow]

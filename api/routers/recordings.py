"""
api/routers/recordings.py — Recording catalogue endpoint.

Endpoint:
  GET /api/recordings   — list all .npy recordings in data/recordings/
"""
from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
from fastapi import APIRouter

from api.config import settings
from api.models.schemas import RecordingInfo, RecordingListResponse

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/recordings", tags=["recordings"])


@router.get("", response_model=RecordingListResponse)
def list_recordings() -> RecordingListResponse:
    """Return all .npy recording files available for replay."""
    recordings_dir = Path(settings.recordings_dir)
    if not recordings_dir.exists():
        return RecordingListResponse(recordings=[], total=0)

    recordings: list[RecordingInfo] = []
    for npy_file in sorted(recordings_dir.glob("*.npy")):
        try:
            data = np.load(str(npy_file), mmap_mode="r")
            duration_s = data.shape[1] / 4.0  # 4 Hz sample rate → seconds
        except Exception:
            duration_s = 0.0
        recordings.append(
            RecordingInfo(
                recording_id=npy_file.stem,
                duration_seconds=round(duration_s, 2),
                file_size_kb=npy_file.stat().st_size // 1024,
            )
        )

    return RecordingListResponse(recordings=recordings, total=len(recordings))

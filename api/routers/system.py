"""
api/routers/system.py — System status endpoint.

Endpoint:
  GET /api/system/startup-status   — SSE stream of startup steps (§11.8)
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/system", tags=["system"])


@router.get("/startup-status")
async def startup_status_sse() -> StreamingResponse:
    """
    Server-Sent Events stream reporting the status of each startup step.
    The frontend uses this to display a loading screen while models are loading.

    Each event is a JSON line: {"step": "...", "status": "ok|error|pending", "detail": "..."}
    """

    async def _event_generator():
        artifacts_dir = Path("artifacts")
        recordings_dir = Path("data/recordings")

        steps = [
            ("production_config", artifacts_dir / "production_config.json"),
            ("production_scaler", artifacts_dir / "production_scaler.pkl"),
            ("production_lr", artifacts_dir / "production_lr.pkl"),
            ("weights_fold0", Path("weights/fold0_best_finetune.pt")),
            ("weights_fold1", Path("weights/fold1_best_finetune.pt")),
            ("weights_fold2", Path("weights/fold2_best_finetune.pt")),
            ("weights_fold3", Path("weights/fold3_best_finetune.pt")),
            ("weights_fold4", Path("weights/fold4_best_finetune.pt")),
            ("recordings_dir", recordings_dir),
        ]

        for step_name, path in steps:
            if path.exists():
                event = {"step": step_name, "status": "ok", "detail": str(path)}
            else:
                event = {"step": step_name, "status": "error", "detail": f"Not found: {path}"}
            data = json.dumps(event)
            yield f"data: {data}\n\n"
            await asyncio.sleep(0.05)   # slight delay for frontend to render each step

        # Count recordings
        npy_count = len(list(recordings_dir.glob("*.npy"))) if recordings_dir.exists() else 0
        yield f"data: {json.dumps({'step': 'ready', 'status': 'ok', 'detail': f'{npy_count} recordings available'})}\n\n"

    return StreamingResponse(
        _event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )

"""
api/routers/websocket.py — WebSocket stream endpoint.

Endpoint:
  WS /ws/stream

Protocol (§11.2):
  1. Accept connection
  2. Register client with broadcaster
  3. Send initial_state immediately (all current BedState snapshots)
  4. Broadcaster drains queue and sends batch_update messages
  5. On disconnect: unregister client
"""
from __future__ import annotations

import dataclasses
import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from api.dependencies import get_broadcaster, get_manager

logger = logging.getLogger(__name__)
router = APIRouter(tags=["websocket"])


@router.websocket("/ws/stream")
async def ws_stream(websocket: WebSocket) -> None:
    """
    WebSocket endpoint for real-time BedState updates.

    On connect: sends initial_state with current snapshots for all beds.
    Ongoing: broadcaster.run() sends batch_update and heartbeat messages.
    """
    broadcaster = websocket.app.state.broadcaster
    manager = websocket.app.state.manager

    await websocket.accept()
    client_id = await broadcaster.register(websocket)
    logger.info("WebSocket connected: client=%s", client_id)

    try:
        # §11.2 — send initial state immediately on connect so frontend
        # can populate cards without waiting for the first 6-second tick.
        current_states = manager.get_bed_states()
        beds_data = [dataclasses.asdict(s) for s in current_states]
        await websocket.send_json({"type": "initial_state", "beds": beds_data})

        # Keep connection alive and handle focus/unfocus messages from client.
        # Client sends: {"type": "focus", "bed_id": "bed_01"}
        #               {"type": "unfocus"}
        async for raw in websocket.iter_text():
            try:
                msg = json.loads(raw)
                msg_type = msg.get("type")
                if msg_type == "focus":
                    bed_id = msg.get("bed_id", "")
                    if bed_id:
                        broadcaster.set_focused_bed(client_id, bed_id)
                elif msg_type == "unfocus":
                    broadcaster.clear_focused_bed(client_id)
            except Exception:
                pass  # malformed client message — ignore

    except WebSocketDisconnect:
        logger.info("WebSocket disconnected: client=%s", client_id)
    except Exception:
        logger.exception("WebSocket error: client=%s", client_id)
    finally:
        await broadcaster.unregister(client_id)

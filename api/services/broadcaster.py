"""
api/services/broadcaster.py — AsyncBroadcaster: thread-safe queue → WebSocket push.

Design:
  PipelineManager.push(state)    — called from ThreadPoolExecutor (sync, thread-safe)
  run()                          — async drain loop, batches pending states per tick
  _heartbeat_loop()              — sends {"type":"heartbeat"} every 5 sec (§11.4)

push() uses queue.Queue.put_nowait — NOT a coroutine.
Do NOT wrap with run_coroutine_threadsafe — push is synchronous by design.
"""
from __future__ import annotations

import asyncio
import dataclasses
import json
import logging
import queue
import time
import uuid
from typing import TYPE_CHECKING

from fastapi import WebSocket
from starlette.websockets import WebSocketState

if TYPE_CHECKING:
    from src.inference.pipeline import BedState

logger = logging.getLogger(__name__)

# How long the drain loop sleeps between queue polls (seconds)
_DRAIN_INTERVAL = 0.05   # 50ms — well within 6-second update cadence


class AsyncBroadcaster:
    """
    Thread-safe queue → async WebSocket broadcast.

    push()  — synchronous, called from thread pool (queue.put_nowait)
    run()   — async drain + heartbeat loop (started as asyncio.create_task)
    """

    def __init__(self) -> None:
        self._queue: queue.Queue = queue.Queue()
        self._clients: dict[str, WebSocket] = {}   # client_id → websocket
        self._running: bool = False

    # ── Primary interface: push from thread pool ──────────────────────────

    def push(self, state: "BedState") -> None:
        """
        Thread-safe. Called from PipelineManager._process_and_broadcast().
        Converts BedState to serialisable dict and enqueues it.
        push() is synchronous — NO asyncio involvement here.
        """
        try:
            d = dataclasses.asdict(state)
            d["_kind"] = "state"
            self._queue.put_nowait(d)
        except queue.Full:
            logger.warning("Broadcaster queue full — dropping BedState for %s", state.bed_id)

    def push_chart_tick(self, bed_id: str, fhr_bpm: float, uc_mmhg: float, t: float) -> None:
        """
        Thread-safe. Called from PipelineManager._process_and_broadcast() at 4 Hz.
        Enqueues a single raw sample for real-time CTG chart streaming.
        Chart tick loss is acceptable — drop silently on full queue.
        """
        try:
            self._queue.put_nowait({
                "_kind": "tick",
                "bed_id": bed_id,
                "fhr": fhr_bpm,
                "uc": uc_mmhg,
                "t": t,
            })
        except queue.Full:
            pass

    # ── WebSocket client management ────────────────────────────────────────

    async def register(self, ws: WebSocket) -> str:
        """Register a new WebSocket client. Returns client_id."""
        client_id = str(uuid.uuid4())[:8]
        self._clients[client_id] = ws
        logger.info("WebSocket client registered: %s (total=%d)", client_id, len(self._clients))
        return client_id

    async def unregister(self, client_id: str) -> None:
        """Remove a disconnected client."""
        self._clients.pop(client_id, None)
        logger.info("WebSocket client unregistered: %s (total=%d)", client_id, len(self._clients))

    # ── Async run loop ─────────────────────────────────────────────────────

    async def run(self) -> None:
        """
        Start drain loop and heartbeat.
        Should be started as asyncio.create_task(broadcaster.run()) in lifespan.
        """
        self._running = True
        logger.info("AsyncBroadcaster: starting drain + heartbeat loops")
        await asyncio.gather(
            self._drain_loop(),
            self._heartbeat_loop(),
        )

    async def stop(self) -> None:
        """Signal loops to exit."""
        self._running = False

    # ── Internal loops ─────────────────────────────────────────────────────

    async def _drain_loop(self) -> None:
        """
        Polls queue every _DRAIN_INTERVAL.
        Separates bed_states (inference results) from chart_ticks (raw 4 Hz samples)
        and sends both in a single batch_update message per cycle.
        """
        while self._running:
            bed_states: list[dict] = []
            chart_ticks: list[dict] = []

            # Drain everything currently in the queue (non-blocking)
            while True:
                try:
                    item = self._queue.get_nowait()
                    if item.pop("_kind", "state") == "tick":
                        chart_ticks.append(item)
                    else:
                        bed_states.append(item)
                except queue.Empty:
                    break

            if (bed_states or chart_ticks) and self._clients:
                msg = {
                    "type": "batch_update",
                    "timestamp": time.time(),
                    "updates": bed_states,
                    "chart_ticks": chart_ticks,
                }
                await self._send_to_all(msg)

            await asyncio.sleep(_DRAIN_INTERVAL)

    async def _heartbeat_loop(self) -> None:
        """Sends {"type": "heartbeat", "ts": ...} every 5 seconds (§11.4)."""
        while self._running:
            await asyncio.sleep(5)
            if self._clients:
                await self._send_to_all({"type": "heartbeat", "ts": time.time()})

    async def _send_to_all(self, msg: dict) -> None:
        """Send a JSON message to all connected clients concurrently.

        Serializes JSON once, sends the same text to all clients in parallel
        with a per-client timeout so one slow client cannot block others.
        """
        if not self._clients:
            return
        text = json.dumps(msg)
        tasks = [
            self._send_one(cid, ws, text)
            for cid, ws in list(self._clients.items())
        ]
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _send_one(self, client_id: str, ws: WebSocket, text: str) -> None:
        """Send pre-serialized text to one client with a 2-second timeout."""
        try:
            if ws.client_state == WebSocketState.CONNECTED:
                await asyncio.wait_for(ws.send_text(text), timeout=2.0)
        except Exception as exc:
            logger.debug("Failed to send to client %s: %s", client_id, exc)
            await self.unregister(client_id)

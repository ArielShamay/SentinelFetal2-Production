"""
api/services/broadcaster.py — AsyncBroadcaster: thread-safe queues → WebSocket push.

Design:
  _queue      — BedState inference results (low volume, ~every 6s per bed)
  _tick_queue — raw chart ticks (high volume, up to 4 Hz × 16 beds × speed)

  push(state)             — called from ThreadPoolExecutor (sync, thread-safe)
  push_chart_tick(...)    — called from event loop in on_sample() (sync, thread-safe)
  run()                   — async drain loop + heartbeat loop
  _heartbeat_loop()       — sends {"type":"heartbeat"} every 5 sec

Per-client focus tracking (Ruba 2):
  register(ws)            — returns client_id; focused_bed_id starts as None (ward view)
  set_focused_bed(id, b)  — client moved to DetailView for bed b; receives full-rate ticks
  clear_focused_bed(id)   — client returned to WardView; receives only ward ticks

Ward downsampling:
  Ward ticks are capped at 4 Hz per bed (≥ 0.25 s between consecutive ward ticks).
  At speed 1× this is already the natural rate; at 10× it reduces wire load by 10×.
  Detail clients receive every tick for their focused bed at full rate.
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

_DRAIN_INTERVAL     = 0.05    # 50 ms — well within 6-second update cadence
_MAX_STATE_QUEUE    = 1_000   # BedState items — low volume, small cap sufficient
_MAX_TICK_QUEUE     = 50_000  # chart ticks   — high volume; large cap for speed bursts
_MAX_STATES_DRAIN   = 128     # states read per drain cycle
_MAX_TICKS_DRAIN    = 4_096   # ticks read per drain cycle (headroom for speed × 16 beds)
_WARD_MIN_INTERVAL  = 0.25    # seconds between consecutive ward ticks per bed (≤ 4 Hz)


class AsyncBroadcaster:
    """
    Thread-safe queues → async WebSocket broadcast.

    push()           — synchronous, called from thread pool (queue.put_nowait)
    push_chart_tick() — synchronous, called from event loop (queue.put_nowait)
    run()            — async drain + heartbeat loop (started as asyncio.create_task)
    """

    def __init__(self) -> None:
        self._queue:      queue.Queue = queue.Queue(maxsize=_MAX_STATE_QUEUE)
        self._tick_queue: queue.Queue = queue.Queue(maxsize=_MAX_TICK_QUEUE)

        # client_id → {"ws": WebSocket, "focused_bed_id": str | None}
        self._clients: dict[str, dict] = {}

        # Last ward-tick time per bed for downsampling
        self._last_ward_t: dict[str, float] = {}

        self._running: bool = False

    # ── Primary interface: push from thread pool / event loop ─────────────

    def push(self, state: "BedState") -> None:
        """
        Thread-safe. Called from PipelineManager._process_and_broadcast().
        Converts BedState to serialisable dict and enqueues it.
        """
        try:
            d = dataclasses.asdict(state)
            self._queue.put_nowait(d)
        except queue.Full:
            logger.warning("Broadcaster state queue full — dropping BedState for %s", state.bed_id)

    def push_chart_tick(self, bed_id: str, fhr_bpm: float, uc_mmhg: float, t: float) -> None:
        """
        Called from event loop in PipelineManager.on_sample() at the raw sample rate.
        Separate queue from BedState results so AI inference load never delays chart ticks.
        Drop silently on full queue (tick loss is acceptable).
        """
        try:
            self._tick_queue.put_nowait({
                "bed_id": bed_id,
                "fhr":    fhr_bpm,
                "uc":     uc_mmhg,
                "t":      t,
            })
        except queue.Full:
            pass

    # ── WebSocket client management ────────────────────────────────────────

    async def register(self, ws: WebSocket) -> str:
        """Register a new WebSocket client. Returns client_id."""
        client_id = str(uuid.uuid4())[:8]
        self._clients[client_id] = {"ws": ws, "focused_bed_id": None}
        logger.info("WebSocket client registered: %s (total=%d)", client_id, len(self._clients))
        return client_id

    async def unregister(self, client_id: str) -> None:
        """Remove a disconnected client."""
        self._clients.pop(client_id, None)
        logger.info("WebSocket client unregistered: %s (total=%d)", client_id, len(self._clients))

    def set_focused_bed(self, client_id: str, bed_id: str) -> None:
        """Mark client as viewing DetailView for bed_id — receives full-rate ticks."""
        if client_id in self._clients:
            self._clients[client_id]["focused_bed_id"] = bed_id
            logger.debug("Client %s focused on bed %s", client_id, bed_id)

    def clear_focused_bed(self, client_id: str) -> None:
        """Client returned to WardView — only ward (downsampled) ticks from now on."""
        if client_id in self._clients:
            self._clients[client_id]["focused_bed_id"] = None
            logger.debug("Client %s unfocused (ward view)", client_id)

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
        Polls both queues every _DRAIN_INTERVAL.

        Ward ticks:   at most 1 per bed every 0.25 s — keeps wire load bounded
                      regardless of replay speed.
        Detail ticks: all ticks for the bed a client is focused on — full rate.
        """
        while self._running:
            # ── 1. Drain BedState updates ──────────────────────────────────
            bed_states: list[dict] = []
            drained = 0
            while drained < _MAX_STATES_DRAIN:
                try:
                    bed_states.append(self._queue.get_nowait())
                    drained += 1
                except queue.Empty:
                    break

            # ── 2. Drain chart ticks ───────────────────────────────────────
            ticks_by_bed: dict[str, list[dict]] = {}
            ward_ticks: list[dict] = []
            drained = 0
            while drained < _MAX_TICKS_DRAIN:
                try:
                    tick = self._tick_queue.get_nowait()
                    drained += 1
                    bid = tick["bed_id"]
                    if bid not in ticks_by_bed:
                        ticks_by_bed[bid] = []
                    ticks_by_bed[bid].append(tick)

                    # Ward downsampling: emit at most one tick per bed per 0.25 s
                    t_val = tick["t"]
                    if t_val - self._last_ward_t.get(bid, -999.0) >= _WARD_MIN_INTERVAL:
                        ward_ticks.append(tick)
                        self._last_ward_t[bid] = t_val
                except queue.Empty:
                    break

            # ── 3. Send per-client (different detail ticks per focused bed) ─
            if not self._clients:
                await asyncio.sleep(_DRAIN_INTERVAL)
                continue

            if bed_states or ticks_by_bed:
                ts = time.time()
                for client_id, info in list(self._clients.items()):
                    focused = info.get("focused_bed_id")
                    detail_ticks = ticks_by_bed.get(focused, []) if focused else []
                    msg = {
                        "type":             "batch_update",
                        "timestamp":        ts,
                        "updates":          bed_states,
                        "ward_chart_ticks": ward_ticks,
                        "chart_ticks":      detail_ticks,
                    }
                    await self._send_one(client_id, info["ws"], json.dumps(msg))

            await asyncio.sleep(_DRAIN_INTERVAL)

    async def _heartbeat_loop(self) -> None:
        """Sends {"type": "heartbeat", "ts": ...} every 5 seconds."""
        while self._running:
            await asyncio.sleep(5)
            if self._clients:
                await self._send_to_all({"type": "heartbeat", "ts": time.time()})

    async def _send_to_all(self, msg: dict) -> None:
        """Serialize once, send to all clients concurrently (used for heartbeat)."""
        if not self._clients:
            return
        text = json.dumps(msg)
        tasks = [
            self._send_one(cid, info["ws"], text)
            for cid, info in list(self._clients.items())
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

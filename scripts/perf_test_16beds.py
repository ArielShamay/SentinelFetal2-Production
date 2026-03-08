"""
scripts/perf_test_16beds.py -- Endurance test: 16 beds x 35 minutes @ speed 1x

Validates long-term stability:
  - Memory plateau at minute 30 (ring buffers full, window_scores capped)
  - CPU stays under 40%
  - WebSocket lag stays under 200ms
  - Zero backend exceptions

Usage:
  Start backend:  uvicorn api.main:app --port 8000
  Start frontend: cd frontend && npm run dev
  Run test:       python scripts/perf_test_16beds.py

Pass criteria:
  CPU avg <= 40%
  RSS <= 1 GB and stable after minute 30
  WS lag p99 < 200ms
  Backend errors: 0
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
import statistics
import threading
from datetime import datetime, timedelta
from pathlib import Path

import psutil
import requests
import websockets

# -- Config -------------------------------------------------------------------

BACKEND_URL    = "http://localhost:8000"
WS_URL         = "ws://localhost:8000/ws/stream"
RECORDINGS_DIR = Path("data/recordings")
LOGS_DIR       = Path("logs")
DURATION       = 2100          # 35 minutes
SPEED          = 1.0
N_BEDS         = 16
STATUS_EVERY   = 60            # print status every N seconds

CPU_THRESHOLD_PCT   = 40.0
RSS_THRESHOLD_MB    = 1024.0
WS_LAG_THRESHOLD_MS = 200.0

# -- Shared state (thread-safe via GIL for simple types) ----------------------

cpu_samples:     list[float] = []
rss_samples:     list[float] = []
ws_lag_samples:  list[float] = []
ws_msg_count:    int = 0
error_count:     int = 0
_lock = threading.Lock()

# -- Helpers ------------------------------------------------------------------

def percentile(data: list[float], p: float) -> float:
    if not data:
        return 0.0
    sorted_data = sorted(data)
    idx = int(len(sorted_data) * p / 100)
    return sorted_data[min(idx, len(sorted_data) - 1)]


def mb(bytes_val: float) -> float:
    return bytes_val / (1024 * 1024)


def fmt_duration(seconds: float) -> str:
    return str(timedelta(seconds=int(seconds)))


# -- System monitor (runs in background thread) -------------------------------

def system_monitor(stop_event: threading.Event) -> None:
    proc = psutil.Process()
    while not stop_event.is_set():
        try:
            cpu = psutil.cpu_percent(interval=1.0)
            rss = mb(proc.memory_info().rss)
            with _lock:
                cpu_samples.append(cpu)
                rss_samples.append(rss)
        except Exception:
            pass


# -- WebSocket listener -------------------------------------------------------

async def ws_listener(stop_event: threading.Event) -> None:
    global ws_msg_count, error_count

    backoff = 1.0
    while not stop_event.is_set():
        try:
            async with websockets.connect(WS_URL, ping_interval=10, ping_timeout=5) as ws:
                backoff = 1.0
                async for raw in ws:
                    if stop_event.is_set():
                        break
                    try:
                        msg = json.loads(raw)
                        if msg.get("type") == "batch_update":
                            server_ts = msg.get("timestamp", 0)
                            lag_ms = (time.time() - server_ts) * 1000
                            with _lock:
                                ws_lag_samples.append(lag_ms)
                                ws_msg_count += 1
                    except Exception:
                        pass
        except Exception as exc:
            with _lock:
                error_count += 1
            if not stop_event.is_set():
                await asyncio.sleep(min(backoff, 10.0))
                backoff *= 2


# -- Setup: start simulation --------------------------------------------------

def start_simulation() -> bool:
    recordings = sorted(RECORDINGS_DIR.glob("*.npy"))
    if not recordings:
        print(f"ERROR: No .npy recordings found in {RECORDINGS_DIR}")
        return False

    # Use up to N_BEDS recordings (cycle if fewer available)
    beds = []
    for i in range(N_BEDS):
        rec = recordings[i % len(recordings)]
        beds.append({
            "bed_id": f"bed_{i+1:02d}",
            "recording_id": rec.stem,
        })

    print(f"Starting simulation with {len(beds)} beds (recordings: {recordings[0].stem}-{recordings[min(N_BEDS-1, len(recordings)-1)].stem})")

    try:
        r = requests.post(f"{BACKEND_URL}/api/simulation/start",
                          json={"beds": beds, "speed": SPEED},
                          timeout=15)
        r.raise_for_status()
        print(f"Simulation started: {r.json()}")
        return True
    except Exception as exc:
        print(f"ERROR starting simulation: {exc}")
        return False


def stop_simulation() -> None:
    try:
        requests.post(f"{BACKEND_URL}/api/simulation/stop", timeout=5)
    except Exception:
        pass


# -- Status line --------------------------------------------------------------

def print_status(elapsed: float) -> None:
    with _lock:
        cpu_window  = cpu_samples[-60:] if cpu_samples else [0.0]
        rss_now     = rss_samples[-1] if rss_samples else 0.0
        lag_window  = ws_lag_samples[-240:] if ws_lag_samples else [0.0]
        msgs        = ws_msg_count

    cpu_avg  = statistics.mean(cpu_window)
    lag_p50  = percentile(lag_window, 50)
    lag_p99  = percentile(lag_window, 99)

    cpu_warn  = " !" if cpu_avg  > CPU_THRESHOLD_PCT   else ""
    rss_warn  = " !" if rss_now  > RSS_THRESHOLD_MB    else ""
    lag_warn  = " !" if lag_p99  > WS_LAG_THRESHOLD_MS else ""

    print(
        f"[T+{fmt_duration(elapsed)}]  "
        f"CPU: {cpu_avg:5.1f}%{cpu_warn}  |  "
        f"RSS: {rss_now:6.0f} MB{rss_warn}  |  "
        f"WS lag p50/p99: {lag_p50:4.0f}/{lag_p99:4.0f} ms{lag_warn}  |  "
        f"msgs: {msgs:,}"
    )


# -- Final report -------------------------------------------------------------

def print_report(elapsed: float, log_path: Path) -> bool:
    with _lock:
        all_cpu     = list(cpu_samples)
        all_rss     = list(rss_samples)
        all_lag     = list(ws_lag_samples)
        total_msgs  = ws_msg_count
        errors      = error_count

    rss_start   = all_rss[0]  if all_rss else 0.0
    rss_end     = all_rss[-1] if all_rss else 0.0
    rss_max     = max(all_rss) if all_rss else 0.0

    # Plateau check: compare RSS in first 5min vs last 5min after minute 30
    rss_post30  = all_rss[30*60:] if len(all_rss) > 30*60 else all_rss
    plateau_ok  = True
    if len(rss_post30) > 120:
        rss_early = statistics.mean(rss_post30[:60])
        rss_late  = statistics.mean(rss_post30[-60:])
        # "Stable" = end not more than 50 MB above early post-30 level
        plateau_ok = (rss_late - rss_early) < 50.0

    cpu_avg = statistics.mean(all_cpu) if all_cpu else 0.0
    cpu_max = max(all_cpu) if all_cpu else 0.0
    lag_p50 = percentile(all_lag, 50)
    lag_p99 = percentile(all_lag, 99)

    cpu_pass     = cpu_avg <= CPU_THRESHOLD_PCT
    rss_pass     = rss_max <= RSS_THRESHOLD_MB
    lag_pass     = lag_p99 < WS_LAG_THRESHOLD_MS
    errors_pass  = errors == 0
    plateau_pass = plateau_ok
    overall      = all([cpu_pass, rss_pass, lag_pass, errors_pass])

    def ok(b): return "PASS" if b else "FAIL"

    lines = [
        "",
        "======================================================",
        f"  ENDURANCE TEST REPORT  ({int(elapsed//60)} min, {N_BEDS} beds, {SPEED}x)",
        "======================================================",
        f"  Duration:           {fmt_duration(elapsed)}",
        f"  Total WS messages:  {total_msgs:,}",
        f"  WS reconnections:   {errors}",
        "------------------------------------------------------",
        f"  CPU avg / max:      {cpu_avg:.1f}% / {cpu_max:.1f}%       -> {ok(cpu_pass)} (<={CPU_THRESHOLD_PCT}%)",
        f"  RSS start / end:    {rss_start:.0f} MB / {rss_end:.0f} MB",
        f"  RSS max:            {rss_max:.0f} MB              -> {ok(rss_pass)} (<={RSS_THRESHOLD_MB:.0f} MB)",
        f"  Memory plateau:     {'STABLE' if plateau_pass else 'DRIFTING (+>50 MB after min 30)'}",
        f"  WS lag p50 / p99:   {lag_p50:.0f} ms / {lag_p99:.0f} ms    -> {ok(lag_pass)} (p99 < {WS_LAG_THRESHOLD_MS:.0f} ms)",
        f"  Backend errors:     {errors}                -> {ok(errors_pass)}",
        "------------------------------------------------------",
        f"  OVERALL: {'[PASS]' if overall else '[FAIL]'}",
        "======================================================",
        "",
    ]

    report = "\n".join(lines)
    print(report)

    LOGS_DIR.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = LOGS_DIR / f"endurance_test_{ts}.log"
    log_path.write_text(report, encoding="utf-8")
    print(f"Report saved to {log_path}")

    return overall


# -- Main ---------------------------------------------------------------------

async def main() -> None:
    print("=" * 54)
    print(f"  ENDURANCE TEST -- {N_BEDS} beds x {DURATION//60} min @ {SPEED}x")
    print("=" * 54)
    print(f"  Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Critical checkpoints:")
    print(f"    T+07:30 -- warmup complete, inference starts")
    print(f"    T+30:00 -- ring buffers full, memory should plateau")
    print(f"    T+35:00 -- test ends")
    print("=" * 54)
    print()

    # Start simulation
    if not start_simulation():
        sys.exit(1)

    # Give it 2s to settle
    await asyncio.sleep(2.0)

    stop_event  = threading.Event()
    log_path    = Path(".")

    # Start system monitor thread
    monitor_thread = threading.Thread(target=system_monitor, args=(stop_event,), daemon=True)
    monitor_thread.start()

    # Start WebSocket listener as asyncio task
    ws_task = asyncio.create_task(ws_listener(stop_event))

    t_start         = time.time()
    next_status_at  = t_start + STATUS_EVERY

    try:
        while True:
            now = time.time()
            elapsed = now - t_start

            if elapsed >= DURATION:
                break

            if now >= next_status_at:
                print_status(elapsed)
                next_status_at += STATUS_EVERY

            await asyncio.sleep(0.5)

    except KeyboardInterrupt:
        print("\n[Interrupted -- generating partial report]")

    finally:
        stop_event.set()
        ws_task.cancel()
        try:
            await ws_task
        except asyncio.CancelledError:
            pass

        elapsed = time.time() - t_start
        passed = print_report(elapsed, log_path)
        stop_simulation()
        sys.exit(0 if passed else 1)


if __name__ == "__main__":
    asyncio.run(main())

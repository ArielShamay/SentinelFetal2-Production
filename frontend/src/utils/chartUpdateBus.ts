// src/utils/chartUpdateBus.ts
// Singleton pub/sub bus with per-bed ring buffer.
//
// publish() always stores data — regardless of whether anyone is subscribed.
// subscribe() registers the callback for LIVE ticks only (no synchronous replay).
// getHistory() returns the full buffer snapshot for deferred initial load.
//
// This bypasses the React render cycle entirely (BUG-10):
//   - Store update triggers re-render of WardView/BedCard cards
//   - Chart update is delivered directly via this bus to useCTGChart
//   - series.update() is called EXACTLY ONCE per WebSocket frame per bed
//   - No zigzag artifacts from double-invoke (React Strict Mode or unrelated re-renders)
//
// History load is intentionally async (requestAnimationFrame in useCTGChart) so
// that navigation transitions paint first and the setData() call never blocks the browser.

type ChartCallback = (fhrVals: number[], ucVals: number[], tStart: number) => void

interface TickRecord {
  fhr: number
  uc: number
  t: number
}

export interface HistorySnapshot {
  fhrVals: number[]
  ucVals: number[]
  tStart: number
}

// 20 minutes × 4 Hz = 4800 ticks per bed (~115 KB total for 4 beds)
const MAX_BUFFER = 4800

class ChartUpdateBus {
  private subs    = new Map<string, ChartCallback>()
  private buffers = new Map<string, TickRecord[]>()

  /**
   * Subscribe a chart handler for LIVE ticks only.
   * Does NOT replay history — call getHistory() + requestAnimationFrame instead.
   * Returns an unsubscribe fn.
   */
  subscribe(bedId: string, cb: ChartCallback): () => void {
    this.subs.set(bedId, cb)
    return () => this.subs.delete(bedId)
  }

  /**
   * Returns a snapshot of the full ring buffer for deferred initial load.
   * Returns null if the buffer is empty.
   */
  getHistory(bedId: string): HistorySnapshot | null {
    const buf = this.buffers.get(bedId)
    if (!buf?.length) return null
    return {
      fhrVals: buf.map(r => r.fhr),
      ucVals:  buf.map(r => r.uc),
      tStart:  buf[0].t,
    }
  }

  /** Publish chart data. Always buffered; delivered to subscriber if present. */
  publish(bedId: string, fhrVals: number[], ucVals: number[], tStart: number): void {
    // Store in ring buffer — always, regardless of subscriber
    if (!this.buffers.has(bedId)) this.buffers.set(bedId, [])
    const buf = this.buffers.get(bedId)!

    const step = 0.25
    for (let i = 0; i < fhrVals.length; i++) {
      buf.push({ fhr: fhrVals[i], uc: ucVals[i], t: tStart + i * step })
    }

    // Trim to MAX_BUFFER (keep most recent).
    // Use slice + replace instead of splice to avoid O(N) in-place shift.
    // Hysteresis of 100 avoids trimming on every single publish call.
    if (buf.length > MAX_BUFFER + 100) {
      this.buffers.set(bedId, buf.slice(-MAX_BUFFER))
    }

    // Deliver to current subscriber (if any)
    this.subs.get(bedId)?.(fhrVals, ucVals, tStart)
  }
}

// Module-level singleton — one bus for the entire app lifetime
export const chartUpdateBus = new ChartUpdateBus()

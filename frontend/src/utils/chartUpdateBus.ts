// src/utils/chartUpdateBus.ts
// Singleton pub/sub bus with per-bed ring buffers.
//
// Two channels:
//   DETAIL channel — full-rate ticks for the focused bed in DetailView.
//     publish() / subscribe() / getHistory()
//     Buffer: 4800 ticks (20 min × 4 Hz) per bed.  O(1) push via RingBuffer.
//
//   WARD channel — downsampled ticks (≤ 4 Hz) for all beds, used by Sparkline.
//     publishWard() / subscribeWard() / getWardHistory()
//     Buffer: 120 ticks (~30 s at 4 Hz / ~2 min at 1 Hz) per bed.
//
// Both channels bypass the React render cycle entirely.
// seeding via initializeFromSnapshot ensures sparklines and the detail chart
// show immediate context after a page refresh.

import { RingBuffer } from './ringBuffer'

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

const MAX_DETAIL_BUFFER = 4800   // 20 min × 4 Hz — O(1) push via RingBuffer
const MAX_WARD_BUFFER   = 120    // ~30 s at 4 Hz / ~2 min at 1 Hz

class ChartUpdateBus {
  // ── Detail channel ────────────────────────────────────────────────────
  private subs    = new Map<string, ChartCallback>()
  private buffers = new Map<string, RingBuffer<TickRecord>>()

  subscribe(bedId: string, cb: ChartCallback): () => void {
    this.subs.set(bedId, cb)
    return () => this.subs.delete(bedId)
  }

  getHistory(bedId: string): HistorySnapshot | null {
    const buf = this.buffers.get(bedId)
    if (!buf || buf.length === 0) return null
    const arr = buf.toArray()
    return {
      fhrVals: arr.map(r => r.fhr),
      ucVals:  arr.map(r => r.uc),
      tStart:  arr[0].t,
    }
  }

  /** Publish full-rate tick(s) for the detail chart. Always buffered (O(1) per tick). */
  publish(bedId: string, fhrVals: number[], ucVals: number[], tStart: number): void {
    if (!this.buffers.has(bedId)) {
      this.buffers.set(bedId, new RingBuffer<TickRecord>(MAX_DETAIL_BUFFER))
    }
    const buf  = this.buffers.get(bedId)!
    const step = 0.25
    for (let i = 0; i < fhrVals.length; i++) {
      buf.push({ fhr: fhrVals[i], uc: ucVals[i], t: tStart + i * step })
    }
    this.subs.get(bedId)?.(fhrVals, ucVals, tStart)
  }

  // ── Ward channel ──────────────────────────────────────────────────────
  private wardSubs    = new Map<string, ChartCallback>()
  private wardBuffers = new Map<string, RingBuffer<TickRecord>>()

  subscribeWard(bedId: string, cb: ChartCallback): () => void {
    this.wardSubs.set(bedId, cb)
    return () => this.wardSubs.delete(bedId)
  }

  getWardHistory(bedId: string): HistorySnapshot | null {
    const buf = this.wardBuffers.get(bedId)
    if (!buf || buf.length === 0) return null
    const arr = buf.toArray()
    return {
      fhrVals: arr.map(r => r.fhr),
      ucVals:  arr.map(r => r.uc),
      tStart:  arr[0].t,
    }
  }

  /** Publish a single downsampled ward tick. Always buffered (O(1)). */
  publishWard(bedId: string, fhr: number, uc: number, t: number): void {
    if (!this.wardBuffers.has(bedId)) {
      this.wardBuffers.set(bedId, new RingBuffer<TickRecord>(MAX_WARD_BUFFER))
    }
    this.wardBuffers.get(bedId)!.push({ fhr, uc, t })
    this.wardSubs.get(bedId)?.([fhr], [uc], t)
  }
}

// Module-level singleton — one bus for the entire app lifetime
export const chartUpdateBus = new ChartUpdateBus()

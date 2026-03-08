// src/stores/bedStore.ts
// Zustand store: all per-bed live data + ring buffers.
// Ring buffer sizes: fhrRing=2400, ucRing=2400 (10 min @ 4Hz), riskHistory=600 (60 min / 6s)

import { create } from 'zustand'
import type { BedUpdate, EventAnnotation } from '../types'
import { RingBuffer } from '../utils/ringBuffer'
import { playAlertTone } from '../utils/alertSound'

// Sizes from PLAN.md §5
const FHR_RING_SIZE = 2400   // 10 min × 60s × 4Hz
const RISK_RING_SIZE = 600   // 60 min × 10 points/min (1 per 6s)

export interface BedData {
  bedId: string
  recordingId: string
  riskScore: number
  alert: boolean
  alertThreshold: number
  windowProb: number
  fhrRing: RingBuffer<number>       // BPM (denormalized)
  ucRing: RingBuffer<number>        // mmHg (denormalized)
  riskHistory: RingBuffer<{ t: number; v: number }>
  // Clinical
  baselineBpm: number
  isTachycardia: boolean
  isBradycardia: boolean
  variabilityAmplitudeBpm: number
  variabilityCategory: number
  nLateDecelerations: number
  nVariableDecelerations: number
  nProlongedDecelerations: number
  maxDecelerationDepthBpm: number
  sinusoidalDetected: boolean
  tachysystoleDetected: boolean
  // Meta
  elapsedSeconds: number
  warmup: boolean
  sampleCount: number
  godModeActive: boolean
  activeEvents: EventAnnotation[]   // from WebSocket, updated each BedUpdate
  riskDelta: number
  lastUpdate: number    // Unix seconds; used by useStaleDetector
}

interface BedStore {
  beds: Map<string, BedData>
  connected: boolean
  lastHeartbeat: number

  updateFromWebSocket: (update: BedUpdate) => void
  initializeFromSnapshot: (updates: BedUpdate[]) => void
  setConnected: (v: boolean) => void
  setHeartbeat: (ts: number) => void
  reset: () => void
}

function applyUpdate(existing: BedData | undefined, u: BedUpdate): BedData {
  const bed: BedData = existing ?? {
    bedId: u.bed_id,
    recordingId: u.recording_id,
    riskScore: 0,
    alert: false,
    alertThreshold: u.alert_threshold,
    windowProb: 0,
    fhrRing: new RingBuffer<number>(FHR_RING_SIZE),
    ucRing: new RingBuffer<number>(FHR_RING_SIZE),
    riskHistory: new RingBuffer<{ t: number; v: number }>(RISK_RING_SIZE),
    baselineBpm: 0,
    isTachycardia: false,
    isBradycardia: false,
    variabilityAmplitudeBpm: 0,
    variabilityCategory: 0,
    nLateDecelerations: 0,
    nVariableDecelerations: 0,
    nProlongedDecelerations: 0,
    maxDecelerationDepthBpm: 0,
    sinusoidalDetected: false,
    tachysystoleDetected: false,
    elapsedSeconds: 0,
    warmup: true,
    sampleCount: 0,
    godModeActive: false,
    activeEvents: [],
    riskDelta: 0,
    lastUpdate: 0,
  }

  const prevAlert = bed.alert

  // Push all new samples into ring buffers (O(1) per sample)
  for (const v of u.fhr_latest) bed.fhrRing.push(v)
  for (const v of u.uc_latest) bed.ucRing.push(v)
  bed.riskHistory.push({ t: u.elapsed_seconds, v: u.risk_score })

  // Overwrite scalar fields
  bed.bedId = u.bed_id
  bed.recordingId = u.recording_id
  bed.riskScore = u.risk_score
  bed.alert = u.alert
  bed.alertThreshold = u.alert_threshold
  bed.windowProb = u.window_prob
  bed.baselineBpm = u.baseline_bpm
  bed.isTachycardia = u.is_tachycardia > 0.5
  bed.isBradycardia = u.is_bradycardia > 0.5
  bed.variabilityAmplitudeBpm = u.variability_amplitude_bpm
  bed.variabilityCategory = u.variability_category
  bed.nLateDecelerations = u.n_late_decelerations
  bed.nVariableDecelerations = u.n_variable_decelerations
  bed.nProlongedDecelerations = u.n_prolonged_decelerations
  bed.maxDecelerationDepthBpm = u.max_deceleration_depth_bpm
  bed.sinusoidalDetected = u.sinusoidal_detected
  bed.tachysystoleDetected = u.tachysystole_detected
  bed.elapsedSeconds = u.elapsed_seconds
  bed.warmup = u.warmup
  bed.sampleCount = u.sample_count
  bed.godModeActive = u.god_mode_active
  bed.activeEvents = u.active_events
  bed.riskDelta = u.risk_delta
  bed.lastUpdate = u.last_update_server_ts > 0
    ? u.last_update_server_ts
    : Date.now() / 1000

  // Sound alert on transition false → true
  if (!prevAlert && u.alert) {
    playAlertTone()
  }

  return bed
}

export const useBedStore = create<BedStore>((set) => ({
  beds: new Map(),
  connected: false,
  lastHeartbeat: 0,

  updateFromWebSocket: (update: BedUpdate) => {
    set(state => {
      const existing = state.beds.get(update.bed_id)
      const updated = applyUpdate(existing, update)
      // Only create a new Map if something visible to WardView changed.
      // This prevents unnecessary re-renders when only internal ring buffers change.
      if (existing
          && existing.riskScore === updated.riskScore
          && existing.alert === updated.alert
          && existing.warmup === updated.warmup
          && existing.sampleCount === updated.sampleCount) {
        state.beds.set(update.bed_id, updated)
        return state  // same reference → no re-render
      }
      const next = new Map(state.beds)
      next.set(update.bed_id, updated)
      return { beds: next }
    })
  },

  initializeFromSnapshot: (updates: BedUpdate[]) => {
    set(() => {
      const next = new Map<string, BedData>()
      for (const u of updates) {
        next.set(u.bed_id, applyUpdate(undefined, u))
      }
      return { beds: next }
    })
  },

  setConnected: (v: boolean) => set({ connected: v }),

  // Heartbeat is transport-level liveness only.
  // Per-bed lastUpdate is set only by actual BedUpdate data — not by heartbeat.
  // This keeps per-bed stale detection independent of WS liveness.
  setHeartbeat: (ts: number) => set({ lastHeartbeat: ts }),

  reset: () => set({ beds: new Map(), connected: false, lastHeartbeat: 0 }),
}))

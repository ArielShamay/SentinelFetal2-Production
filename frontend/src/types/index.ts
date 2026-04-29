// src/types/index.ts
// Mirrors Python api/models/schemas.py exactly — keep in sync.

// ---------------------------------------------------------------------------
// WebSocket message types
// ---------------------------------------------------------------------------

/** Single-bed update inside a batch_update message.
 *  fhr_latest / uc_latest are already denormalized by backend (BPM / mmHg). */
export interface BedUpdate {
  bed_id: string
  recording_id: string
  risk_score: number          // [0, 1]
  alert: boolean
  alert_threshold: number
  window_prob: number

  // Display values — denormalized by backend
  fhr_latest: number[]        // last 24 FHR values in BPM
  uc_latest: number[]         // last 24 UC values in mmHg

  // Clinical features — exact CLINICAL_FEATURE_NAMES order
  baseline_bpm: number
  is_tachycardia: number      // 0 or 1
  is_bradycardia: number      // 0 or 1
  variability_amplitude_bpm: number
  variability_category: number  // 0=absent 1=minimal 2=moderate 3=marked
  n_late_decelerations: number
  n_variable_decelerations: number
  n_prolonged_decelerations: number
  max_deceleration_depth_bpm: number
  sinusoidal_detected: boolean
  tachysystole_detected: boolean

  elapsed_seconds: number
  warmup: boolean
  sample_count: number

  // God Mode fields (always present, default-falsy)
  god_mode_active: boolean
  active_events: EventAnnotation[]
  risk_delta: number
  last_update_server_ts: number
}

/** Single raw CTG sample emitted at 4 Hz for smooth chart rendering.
 *  Decoupled from inference — arrives every sample regardless of inference stride. */
export interface ChartTick {
  bed_id: string
  fhr: number    // BPM (denormalized)
  uc: number     // mmHg (denormalized)
  t: number      // elapsed_seconds — recording timeline, consistent with BedUpdate
}

export interface BatchUpdateMessage {
  type: 'batch_update'
  timestamp: number
  updates: BedUpdate[]
  ward_chart_ticks: ChartTick[]  // downsampled ≤ 4 Hz per bed — all clients, for mini-strips
  chart_ticks: ChartTick[]       // full-rate ticks for focused bed in DetailView only
}

export interface InitialStateMessage {
  type: 'initial_state'
  beds: BedUpdate[]
}

export interface HeartbeatMessage {
  type: 'heartbeat'
  ts: number
}

/** Discriminated union of all WebSocket messages from server */
export type WSMessage = BatchUpdateMessage | InitialStateMessage | HeartbeatMessage

// ---------------------------------------------------------------------------
// REST response types
// ---------------------------------------------------------------------------

export interface SimulationStatus {
  running: boolean
  paused: boolean
  bed_count: number
  speed: number
  active_bed_ids: string[]
  tick_count: number
  elapsed_seconds: number
}

export interface RecordingInfo {
  recording_id: string
  duration_seconds: number
  file_size_kb: number
}

export interface AlertEventSchema {
  bed_id: string
  timestamp: number
  risk_score: number
  alert_on: boolean
  elapsed_s: number
}

export interface AlertHistoryResponse {
  bed_id: string
  events: AlertEventSchema[]
}

/** Annotation for a God Mode injected event on the CTG timeline.
 *  Mirrors Python src/god_mode/types.py EventAnnotation dataclass exactly. */
export interface EventAnnotation {
  event_id: string
  event_type: string
  start_sample: number
  end_sample: number | null
  still_ongoing: boolean
  description: string
  timeline_summary: string          // "Started 00:12:34 | Duration: 00:03:20"
  detected_details: Record<string, number>  // {feature: overridden_value}
}

// ---------------------------------------------------------------------------
// God Mode REST types
// ---------------------------------------------------------------------------

export interface InjectResponse {
  event_id: string
  status: string
  signal_swapped: boolean
  start_sample: number
}

export interface GodModeStatus {
  enabled: boolean
  signal_swap_available: boolean
  available_event_types: string[]   // event types that have catalog entries (★)
}

export interface GodModeEventRecord {
  event_id: string
  bed_id: string
  event_type: string
  start_sample: number
  end_sample: number | null
  severity: number
  description: string
  signal_swapped: boolean
  original_recording_id: string | null
}

export interface EndEventResponse {
  status: string              // "ended" | "not_found"
  recording_restored: boolean
}

/**
 * BedState is the canonical live snapshot of a single bed as received from the
 * server.  It is identical to BedUpdate (the WS wire format) — this alias
 * exists so stores and components can import a semantically distinct name.
 */
export type BedState = BedUpdate

// src/components/god-mode/GodModePanel.tsx
// God Mode injection panel — PIN unlock, event type selection, severity/duration,
// active events list with stop controls.

import React, { useEffect, useState } from 'react'
import toast from 'react-hot-toast'
import { useBedStore } from '../../stores/bedStore'
import { useUIStore } from '../../stores/uiStore'
import type { GodModeStatus, InjectResponse, EndEventResponse } from '../../types'
import { DetectionDetail } from './DetectionDetail'

// ── Constants ──────────────────────────────────────────────────────────────

const EVENT_TYPE_LABELS: Record<string, string> = {
  late_decelerations:    'Late Decels',
  variable_decelerations:'Variable Decels',
  prolonged_deceleration:'Prolonged Decel',
  sinusoidal_pattern:    'Sinusoidal',
  tachysystole:          'Tachysystole',
  bradycardia:           'Bradycardia',
  tachycardia:           'Tachycardia',
  low_variability:       'Low Variability',
  combined_severe:       'Combined Severe',
}

const ALL_EVENT_TYPES = Object.keys(EVENT_TYPE_LABELS)

const DURATION_OPTIONS: { label: string; value: number | null }[] = [
  { label: '1 דקה',   value: 60 },
  { label: '2 דקות',  value: 120 },
  { label: '5 דקות',  value: 300 },
  { label: '10 דקות', value: 600 },
  { label: 'Ongoing', value: null },
]

// ── API helper ─────────────────────────────────────────────────────────────

async function godFetch<T>(
  path: string,
  pin: string,
  options?: RequestInit,
): Promise<T> {
  const resp = await fetch(`/api/god-mode${path}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      'X-God-Mode-Pin': pin,
      ...(options?.headers ?? {}),
    },
  })
  if (!resp.ok) {
    const text = await resp.text()
    throw new Error(`${resp.status}: ${text}`)
  }
  return resp.json() as Promise<T>
}

// ── Component ──────────────────────────────────────────────────────────────

interface Props {
  bedId: string
}

export const GodModePanel: React.FC<Props> = ({ bedId }) => {
  const { godModePin, godModeUnlocked, setGodModePin, clearGodModePin } = useUIStore()
  const bed = useBedStore(s => s.beds.get(bedId))

  const [pinInput, setPinInput]       = useState('')
  const [pinError, setPinError]       = useState(false)
  const [status, setStatus]           = useState<GodModeStatus | null>(null)
  const [selectedType, setSelectedType] = useState('late_decelerations')
  const [severity, setSeverity]       = useState(0.85)
  const [durationSec, setDurationSec] = useState<number | null>(120)
  const [loading, setLoading]         = useState(false)
  const [expandedId, setExpandedId]   = useState<string | null>(null)

  // Load status whenever PIN becomes available
  useEffect(() => {
    if (!godModeUnlocked || !godModePin) return
    godFetch<GodModeStatus>('/status', godModePin)
      .then(setStatus)
      .catch(() => {/* status is optional */})
  }, [godModeUnlocked, godModePin])

  // ── PIN unlock ──────────────────────────────────────────────────
  async function handleUnlock() {
    const trimmed = pinInput.trim()
    if (!trimmed) return
    setLoading(true)
    setPinError(false)
    try {
      const s = await godFetch<GodModeStatus>('/status', trimmed)
      setGodModePin(trimmed)
      setStatus(s)
      setPinInput('')
      toast.success('God Mode unlocked')
    } catch {
      setPinError(true)
    } finally {
      setLoading(false)
    }
  }

  // ── Inject ─────────────────────────────────────────────────────
  async function handleInject() {
    if (!godModePin) return
    setLoading(true)
    try {
      const resp = await godFetch<InjectResponse>('/inject', godModePin, {
        method: 'POST',
        body: JSON.stringify({
          bed_id: bedId,
          event_type: selectedType,
          severity,
          duration_seconds: durationSec,
          description: '',
        }),
      })
      const label = EVENT_TYPE_LABELS[selectedType] ?? selectedType
      if (resp.signal_swapped) {
        toast.success(`Signal + Override: ${label}`)
      } else {
        toast(`Override only: ${label}`, { icon: '' })
      }
    } catch (err) {
      toast.error(`Inject failed: ${err instanceof Error ? err.message : String(err)}`)
    } finally {
      setLoading(false)
    }
  }

  // ── Stop event ─────────────────────────────────────────────────
  async function handleStop(eventId: string) {
    if (!godModePin) return
    try {
      const resp = await godFetch<EndEventResponse>(
        `/events/${eventId}?bed_id=${encodeURIComponent(bedId)}`,
        godModePin,
        { method: 'DELETE' },
      )
      if (resp.recording_restored) {
        toast.success('הקלטה מקורית שוחזרה')
      } else {
        toast('אירוע הסתיים')
      }
      if (expandedId === eventId) setExpandedId(null)
    } catch (err) {
      toast.error(`Stop failed: ${err instanceof Error ? err.message : String(err)}`)
    }
  }

  // ── Clear all ──────────────────────────────────────────────────
  async function handleClearAll() {
    if (!godModePin) return
    try {
      await godFetch(`/clear/${encodeURIComponent(bedId)}`, godModePin, { method: 'DELETE' })
      toast.success('כל האירועים נוקו')
      setExpandedId(null)
    } catch (err) {
      toast.error(`Clear failed: ${err instanceof Error ? err.message : String(err)}`)
    }
  }

  const activeEvents = bed?.activeEvents ?? []

  // ── Render: PIN lock screen ────────────────────────────────────
  if (!godModeUnlocked) {
    return (
      <div className="rounded border border-gray-200 bg-gray-50 p-4">
        <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-3">
          God Mode
        </p>
        <div className="flex gap-2 items-center">
          <input
            type="password"
            placeholder="Enter PIN"
            value={pinInput}
            onChange={e => { setPinInput(e.target.value); setPinError(false) }}
            onKeyDown={e => e.key === 'Enter' && handleUnlock()}
            className={[
              'flex-1 text-sm px-3 py-1.5 border rounded font-mono bg-white',
              pinError ? 'border-gray-900' : 'border-gray-300',
            ].join(' ')}
          />
          <button
            onClick={handleUnlock}
            disabled={loading}
            className="px-3 py-1.5 text-sm bg-gray-900 text-white rounded hover:bg-gray-700 disabled:opacity-50"
          >
            Unlock
          </button>
        </div>
        {pinError && (
          <p className="text-xs text-gray-900 mt-1 font-medium">PIN שגוי</p>
        )}
      </div>
    )
  }

  // ── Render: main panel ─────────────────────────────────────────
  return (
    <div className="rounded border border-gray-200 bg-gray-50 p-4 space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide">
          God Mode
          {bed?.godModeActive && (
            <span className="ml-2 inline-block px-1.5 py-0.5 text-xs bg-gray-900 text-white rounded">
              ACTIVE
            </span>
          )}
        </p>
        <button
          onClick={clearGodModePin}
          className="text-xs text-gray-400 hover:text-gray-700 underline"
        >
          Lock
        </button>
      </div>

      {/* Event type buttons */}
      <div>
        <p className="text-xs text-gray-500 mb-1.5">סוג אירוע</p>
        <div className="flex flex-wrap gap-1.5">
          {ALL_EVENT_TYPES.map(type => {
            const hasCatalog = status?.available_event_types.includes(type) ?? false
            const isSelected = selectedType === type
            return (
              <button
                key={type}
                onClick={() => setSelectedType(type)}
                title={hasCatalog ? 'Signal swap available' : 'Feature override only'}
                className={[
                  'px-2 py-1 text-xs border rounded transition-colors',
                  isSelected
                    ? 'bg-gray-900 text-white border-gray-900'
                    : 'bg-white text-gray-700 border-gray-200 hover:bg-gray-100',
                ].join(' ')}
              >
                {hasCatalog && <span className="mr-0.5">★</span>}
                {EVENT_TYPE_LABELS[type]}
              </button>
            )
          })}
        </div>
      </div>

      {/* Severity + Duration row */}
      <div className="flex flex-wrap gap-4 items-end">
        <div className="flex-1 min-w-[140px]">
          <label className="text-xs text-gray-500 block mb-1">
            עוצמה: <span className="font-mono font-semibold text-gray-900">{severity.toFixed(2)}</span>
          </label>
          <input
            type="range"
            min={0.5}
            max={1.0}
            step={0.05}
            value={severity}
            onChange={e => setSeverity(parseFloat(e.target.value))}
            className="w-full accent-gray-900"
          />
          <div className="flex justify-between text-xs text-gray-400 mt-0.5">
            <span>0.50</span><span>1.00</span>
          </div>
        </div>

        <div>
          <label className="text-xs text-gray-500 block mb-1">משך</label>
          <select
            value={durationSec ?? 'ongoing'}
            onChange={e => setDurationSec(e.target.value === 'ongoing' ? null : Number(e.target.value))}
            className="text-xs border border-gray-200 rounded px-2 py-1.5 bg-white"
          >
            {DURATION_OPTIONS.map(opt => (
              <option key={String(opt.value)} value={opt.value ?? 'ongoing'}>
                {opt.label}
              </option>
            ))}
          </select>
        </div>

        <button
          onClick={handleInject}
          disabled={loading}
          className="px-4 py-1.5 text-sm font-medium bg-gray-900 text-white rounded hover:bg-gray-700 disabled:opacity-50"
        >
          הזרק אירוע
        </button>
      </div>

      {/* Active events list */}
      {activeEvents.length > 0 && (
        <div>
          <div className="flex items-center justify-between mb-1.5">
            <p className="text-xs text-gray-500">אירועים פעילים</p>
            <button
              onClick={handleClearAll}
              className="text-xs text-gray-400 hover:text-gray-700 underline"
            >
              נקה הכל
            </button>
          </div>

          <div className="space-y-1.5">
            {activeEvents.map(event => (
              <div
                key={event.event_id}
                className="border-l-2 border-gray-900 bg-white rounded-r border border-gray-200 overflow-hidden"
              >
                {/* Event row */}
                <div
                  className="flex items-center gap-2 px-3 py-2 cursor-pointer hover:bg-gray-50"
                  onClick={() => setExpandedId(expandedId === event.event_id ? null : event.event_id)}
                >
                  <span className="text-xs font-medium text-gray-900 flex-1">
                    {EVENT_TYPE_LABELS[event.event_type] ?? event.event_type}
                  </span>
                  <span className={[
                    'text-xs px-1 rounded',
                    event.still_ongoing
                      ? 'bg-gray-900 text-white'
                      : 'bg-gray-200 text-gray-600',
                  ].join(' ')}>
                    {event.still_ongoing ? 'ongoing' : 'ended'}
                  </span>
                  <span className="text-xs text-gray-400 font-mono truncate max-w-[140px]">
                    {event.timeline_summary}
                  </span>
                  <button
                    onClick={e => { e.stopPropagation(); handleStop(event.event_id) }}
                    className="text-xs px-2 py-0.5 border border-gray-300 rounded hover:bg-gray-100 text-gray-600 flex-shrink-0"
                  >
                    עצור
                  </button>
                </div>

                {/* Expandable detected_details */}
                {expandedId === event.event_id && (
                  <div className="px-3 pb-2 border-t border-gray-100">
                    <DetectionDetail detectedDetails={event.detected_details} />
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

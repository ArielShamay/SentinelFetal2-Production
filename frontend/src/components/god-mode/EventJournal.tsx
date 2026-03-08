// src/components/god-mode/EventJournal.tsx
// Historical God Mode event log for a bed — loads from REST, manual refresh.

import React, { useEffect, useState } from 'react'
import type { GodModeEventRecord } from '../../types'

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

function samplesToTime(samples: number): string {
  const totalSec = Math.floor(samples / 4)
  const mm = Math.floor(totalSec / 60).toString().padStart(2, '0')
  const ss = (totalSec % 60).toString().padStart(2, '0')
  return `${mm}:${ss}`
}

interface Props {
  bedId: string
  pin: string | null
}

export const EventJournal: React.FC<Props> = ({ bedId, pin }) => {
  const [events, setEvents] = useState<GodModeEventRecord[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function load() {
    if (!pin) return
    setLoading(true)
    setError(null)
    try {
      const resp = await fetch(`/api/god-mode/events?bed_id=${encodeURIComponent(bedId)}`, {
        headers: { 'X-God-Mode-Pin': pin },
      })
      if (!resp.ok) throw new Error(`${resp.status}`)
      const data = await resp.json() as GodModeEventRecord[]
      setEvents(data)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'שגיאה')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [bedId, pin])

  if (!pin) return null

  return (
    <div className="rounded border border-gray-200 bg-gray-50 p-4">
      <div className="flex items-center justify-between mb-3">
        <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide">
          Event Journal
        </p>
        <button
          onClick={load}
          disabled={loading}
          className="text-xs text-gray-500 hover:text-gray-800 underline disabled:opacity-50"
        >
          {loading ? 'טוען…' : 'רענן'}
        </button>
      </div>

      {error && (
        <p className="text-xs text-gray-600 mb-2">שגיאה: {error}</p>
      )}

      {events.length === 0 && !loading && (
        <p className="text-xs text-gray-400">אין אירועים מתועדים</p>
      )}

      {events.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-gray-200 text-gray-400 text-left">
                <th className="pb-1 pr-3 font-medium">סוג</th>
                <th className="pb-1 pr-3 font-medium">התחלה</th>
                <th className="pb-1 pr-3 font-medium">סיום</th>
                <th className="pb-1 pr-3 font-medium">עוצמה</th>
                <th className="pb-1 font-medium">אות</th>
              </tr>
            </thead>
            <tbody>
              {events.map(e => (
                <tr key={e.event_id} className="border-t border-gray-100 hover:bg-white">
                  <td className="py-1 pr-3 font-medium text-gray-800">
                    {EVENT_TYPE_LABELS[e.event_type] ?? e.event_type}
                  </td>
                  <td className="py-1 pr-3 font-mono text-gray-600">
                    {samplesToTime(e.start_sample)}
                  </td>
                  <td className="py-1 pr-3 font-mono text-gray-600">
                    {e.end_sample !== null ? samplesToTime(e.end_sample) : 'ongoing'}
                  </td>
                  <td className="py-1 pr-3 font-mono text-gray-600">
                    {e.severity.toFixed(2)}
                  </td>
                  <td className="py-1">
                    {e.signal_swapped
                      ? <span className="px-1 bg-gray-900 text-white rounded text-xs">Signal</span>
                      : <span className="px-1 bg-gray-200 text-gray-600 rounded text-xs">Override</span>
                    }
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

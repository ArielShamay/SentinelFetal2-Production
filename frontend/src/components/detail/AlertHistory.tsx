// src/components/detail/AlertHistory.tsx
// Fetches GET /api/beds/{bed_id}/alerts and renders a scrollable table.

import React, { useEffect, useState } from 'react'
import type { AlertHistoryResponse, AlertEventSchema } from '../../types'
import { formatIsraelTime, formatIsraelTimeWithDate } from '../../utils/israelTime'

interface Props {
  bedId: string
}

export const AlertHistory: React.FC<Props> = ({ bedId }) => {
  const [events, setEvents] = useState<AlertEventSchema[]>([])
  const [error, setError]   = useState<string | null>(null)

  useEffect(() => {
    if (!bedId) return
    setError(null)
    fetch(`/api/beds/${encodeURIComponent(bedId)}/alerts`)
      .then(r => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`)
        return r.json() as Promise<AlertHistoryResponse>
      })
      .then(data => setEvents(data.events))
      .catch((e: unknown) => setError(e instanceof Error ? e.message : 'Error'))
  }, [bedId])

  return (
    <section className="rounded border border-gray-200 p-3 bg-white">
      <h3 className="text-xs font-semibold uppercase tracking-wide text-gray-500 mb-2">
        Alert History
      </h3>

      {error && <p className="text-xs text-gray-500">{error}</p>}

      {!error && events.length === 0 && (
        <p className="text-xs text-gray-400">No alerts recorded.</p>
      )}

      {events.length > 0 && (
        <div className="overflow-y-auto max-h-40">
          <table className="w-full text-xs border-collapse">
            <thead>
              <tr className="text-gray-500 border-b border-gray-200">
                <th className="text-left pr-2 py-0.5 font-medium">Time (IST)</th>
                <th className="text-left pr-2 py-0.5 font-medium">Score</th>
                <th className="text-left py-0.5 font-medium">Alert</th>
              </tr>
            </thead>
            <tbody>
              {events.map((ev, i) => (
                <tr key={i} className="border-b border-gray-50 last:border-0">
                  <td className="pr-2 py-0.5 font-mono" title={formatIsraelTimeWithDate(ev.timestamp)}>
                    {formatIsraelTime(ev.timestamp, true)}
                  </td>
                  <td className="pr-2 py-0.5 font-mono">{(ev.risk_score * 100).toFixed(0)}%</td>
                  <td className="py-0.5 text-gray-700">{ev.alert_on ? 'ON' : 'OFF'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}

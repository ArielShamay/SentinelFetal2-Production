// src/components/detail/DetectionList.tsx
// Session-local list of model/rule events detected by the explainability layer.

import React from 'react'
import type { DetectionEvent } from '../../types'

interface Props {
  events: DetectionEvent[]
  onSelect?: (event: DetectionEvent) => void
}

const LABELS: Record<string, string> = {
  lr_high_risk: 'RISK',
  late_deceleration: 'LATE',
  variable_deceleration: 'VAR',
  prolonged_deceleration: 'PROL',
  bradycardia: 'BRAD',
  tachycardia: 'TACH',
  low_variability: 'LOWV',
  sinusoidal: 'SIN',
  tachysystole: 'TS',
}

export const DetectionList: React.FC<Props> = ({ events, onSelect }) => {
  const sorted = [...events].sort((a, b) => b.start_sample - a.start_sample)

  return (
    <section className="rounded border border-gray-200 p-3 bg-white">
      <h3 className="text-xs font-semibold uppercase tracking-wide text-gray-500 mb-2">
        אירועים שזוהו ({events.length})
      </h3>

      {sorted.length === 0 ? (
        <p className="text-xs text-gray-400">לא זוהו אירועים מאז תחילת הסשן</p>
      ) : (
        <div className="flex flex-col gap-1.5 max-h-56 overflow-y-auto">
          {sorted.map(event => {
            const label = LABELS[event.event_type] ?? event.event_type.slice(0, 4).toUpperCase()
            const top = event.top_contributions[0]
            return (
              <button
                key={event.event_id}
                type="button"
                onClick={() => onSelect?.(event)}
                className="text-left rounded border border-gray-100 hover:border-gray-400 p-2 transition-colors"
              >
                <div className="flex items-center gap-2">
                  <span
                    className={[
                      'text-[10px] font-mono px-1.5 py-0.5 rounded border',
                      event.still_ongoing
                        ? 'bg-gray-900 text-white border-gray-900'
                        : 'bg-white text-gray-700 border-gray-300',
                    ].join(' ')}
                  >
                    {label}
                  </span>
                  <span className="text-xs font-medium text-gray-900 truncate">
                    {event.description}
                  </span>
                </div>
                <div className="mt-1 text-[11px] text-gray-500 font-mono">
                  {event.timeline_summary}
                </div>
                {top && event.source === 'model' && (
                  <div className="mt-1 text-[11px] text-gray-500 truncate">
                    סיבה עיקרית: {top.friendly_label}
                  </div>
                )}
              </button>
            )
          })}
        </div>
      )}
    </section>
  )
}

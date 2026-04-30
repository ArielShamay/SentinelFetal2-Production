// src/components/detail/ExplanationPanel.tsx
// Shows the top LR feature contributions for the current risk score.

import React from 'react'
import type { FeatureContribution } from '../../types'

interface Props {
  topContributions: FeatureContribution[]
  warmup?: boolean
}

function formatRawValue(item: FeatureContribution): string {
  const boolFeatures = new Set([
    'is_tachycardia',
    'is_bradycardia',
    'sinusoidal_detected',
    'tachysystole_detected',
  ])
  if (boolFeatures.has(item.name)) return item.raw_value > 0.5 ? 'כן' : 'לא'
  if (item.name === 'variability_category') {
    const labels = ['נעדרת', 'מינימלית', 'מתונה', 'מסומנת']
    return labels[Math.round(item.raw_value)] ?? item.raw_value.toFixed(1)
  }
  if (item.name.includes('fraction')) return `${(item.raw_value * 100).toFixed(1)}%`
  if (item.name.includes('bpm') || item.name.includes('depth')) return item.raw_value.toFixed(0)
  return item.raw_value.toFixed(2)
}

const EVENT_LABELS: Array<{ code: string; title: string }> = [
  { code: 'RISK', title: 'זיהוי סיכון של המודל' },
  { code: 'LATE', title: 'האטה מאוחרת' },
  { code: 'VAR', title: 'האטה משתנה' },
  { code: 'PROL', title: 'האטה ממושכת' },
  { code: 'BRAD', title: 'ברדיקרדיה' },
  { code: 'TACH', title: 'טכיקרדיה' },
  { code: 'LOWV', title: 'שונות נמוכה' },
  { code: 'SIN', title: 'דפוס סינוסואידלי' },
  { code: 'TS', title: 'טכיסיסטולה' },
]

export const ExplanationPanel: React.FC<Props> = ({ topContributions, warmup }) => {
  const items = topContributions.slice(0, 5)
  const maxAbs = Math.max(0.0001, ...items.map(item => Math.abs(item.contribution)))

  return (
    <section className="rounded border border-gray-200 p-3 bg-white">
      <h3 className="text-xs font-semibold uppercase tracking-wide text-gray-500 mb-2">
        גורמים מובילים לציון הסיכון
      </h3>

      <div className="flex flex-col gap-3">
        {warmup || items.length === 0 ? (
          <p className="text-xs text-gray-400">ממתין להתחממות...</p>
        ) : (
          <div className="flex flex-col gap-2">
            {items.map(item => {
              const strength = Math.max(6, Math.round((Math.abs(item.contribution) / maxAbs) * 100))
              const arrow = item.direction === 'increases_risk' ? '↑' : '↓'
              return (
                <div key={item.name} className="flex flex-col gap-1">
                  <div className="flex items-center gap-2">
                    <span className="text-xs text-gray-900 font-medium truncate">
                      {item.friendly_label}
                    </span>
                    <span className="ml-auto text-xs font-mono text-gray-500">
                      {formatRawValue(item)} {arrow}
                    </span>
                  </div>
                  <div className="h-1.5 rounded bg-gray-100 overflow-hidden">
                    <div
                      className="h-full rounded bg-gray-900"
                      style={{ width: `${strength}%`, opacity: item.direction === 'increases_risk' ? 0.85 : 0.35 }}
                    />
                  </div>
                </div>
              )
            })}
          </div>
        )}

        <div className="border-t border-gray-100 pt-3">
          <h4 className="text-[11px] font-semibold uppercase tracking-wide text-gray-500 mb-2">
            מקרא סימונים בגרף
          </h4>
          <div className="grid grid-cols-1 gap-1.5 text-[11px] text-gray-600">
            <div className="flex items-center gap-2">
              <span className="w-8 h-3 rounded border border-red-300 bg-red-100" aria-hidden="true" />
              <span>זיהוי סיכון מודל (RISK)</span>
            </div>
            <div className="flex items-center gap-2">
              <span
                className="w-8 h-3 rounded border border-red-200"
                style={{
                  background:
                    'repeating-linear-gradient(135deg, rgba(220,38,38,0.16) 0 3px, transparent 3px 7px)',
                }}
                aria-hidden="true"
              />
              <span>האטות (LATE / VAR / PROL)</span>
            </div>
            <div className="flex items-center gap-2">
              <span
                className="w-8 h-3 rounded border border-red-200"
                style={{
                  background:
                    'radial-gradient(circle, rgba(220,38,38,0.34) 1px, transparent 1.5px)',
                  backgroundSize: '6px 6px',
                }}
                aria-hidden="true"
              />
              <span>מצב מתמשך (BRAD / TACH / LOWV / SIN / TS)</span>
            </div>
            <div className="flex items-center gap-2">
              <span className="w-8 h-0.5 rounded bg-red-600" aria-hidden="true" />
              <span>מקטע פעיל של אירוע על קו הדופק</span>
            </div>
          </div>
          <div className="mt-2 flex flex-wrap gap-1">
            {EVENT_LABELS.map(item => (
              <span
                key={item.code}
                title={item.title}
                className="font-mono text-[10px] px-1.5 py-0.5 rounded border border-gray-200 text-gray-600 bg-gray-50"
              >
                {item.code}
              </span>
            ))}
          </div>
        </div>
      </div>
    </section>
  )
}

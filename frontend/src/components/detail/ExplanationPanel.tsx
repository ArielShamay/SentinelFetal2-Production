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

export const ExplanationPanel: React.FC<Props> = ({ topContributions, warmup }) => {
  const items = topContributions.slice(0, 5)
  const maxAbs = Math.max(0.0001, ...items.map(item => Math.abs(item.contribution)))

  return (
    <section className="rounded border border-gray-200 p-3 bg-white">
      <h3 className="text-xs font-semibold uppercase tracking-wide text-gray-500 mb-2">
        גורמים מובילים לציון הסיכון
      </h3>

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
    </section>
  )
}

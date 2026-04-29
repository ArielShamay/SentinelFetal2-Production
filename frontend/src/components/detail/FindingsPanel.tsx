// src/components/detail/FindingsPanel.tsx
// Displays the 11 clinical feature flags for a single bed.

import React from 'react'
import type { BedData } from '../../stores/bedStore'
import type { FeatureContribution } from '../../types'

interface Props {
  bed: BedData
  topContributions?: FeatureContribution[]
}

function Row({
  label,
  value,
  highlighted,
}: {
  label: string
  value: React.ReactNode
  highlighted?: boolean
}) {
  return (
    <div
      className={[
        'flex justify-between items-center py-0.5 border-b border-gray-100 last:border-0 pl-2',
        highlighted ? 'border-l-4 border-l-gray-900' : 'border-l-4 border-l-transparent',
      ].join(' ')}
    >
      <span className="text-xs text-gray-500">{label}</span>
      <span className="text-xs font-mono text-gray-800">{value}</span>
    </div>
  )
}

function Flag({ on }: { on: boolean }) {
  return <span className={on ? 'font-semibold text-gray-900' : 'text-gray-400'}>{on ? 'Yes' : 'No'}</span>
}

export const FindingsPanel: React.FC<Props> = ({ bed, topContributions = [] }) => {
  const highlighted = new Set(topContributions.map(item => item.name))
  const isHighlighted = (name: string) => highlighted.has(name)

  return (
    <section className="rounded border border-gray-200 p-3 bg-white">
      <h3 className="text-xs font-semibold uppercase tracking-wide text-gray-500 mb-2">Clinical Findings</h3>
      <Row label="Baseline (BPM)"          value={bed.baselineBpm.toFixed(1)} highlighted={isHighlighted('baseline_bpm')} />
      <Row label="Tachycardia"             value={<Flag on={bed.isTachycardia} />} highlighted={isHighlighted('is_tachycardia')} />
      <Row label="Bradycardia"             value={<Flag on={bed.isBradycardia} />} highlighted={isHighlighted('is_bradycardia')} />
      <Row label="Variability (BPM)"       value={bed.variabilityAmplitudeBpm.toFixed(1)} highlighted={isHighlighted('variability_amplitude_bpm')} />
      <Row label="Variability category"    value={bed.variabilityCategory} highlighted={isHighlighted('variability_category')} />
      <Row label="Late decelerations"      value={bed.nLateDecelerations} highlighted={isHighlighted('n_late_decelerations')} />
      <Row label="Variable decelerations"  value={bed.nVariableDecelerations} highlighted={isHighlighted('n_variable_decelerations')} />
      <Row label="Prolonged decelerations" value={bed.nProlongedDecelerations} highlighted={isHighlighted('n_prolonged_decelerations')} />
      <Row label="Max decel depth (BPM)"   value={bed.maxDecelerationDepthBpm.toFixed(1)} highlighted={isHighlighted('max_deceleration_depth_bpm')} />
      <Row label="Sinusoidal"              value={<Flag on={bed.sinusoidalDetected} />} highlighted={isHighlighted('sinusoidal_detected')} />
      <Row label="Tachysystole"            value={<Flag on={bed.tachysystoleDetected} />} highlighted={isHighlighted('tachysystole_detected')} />
    </section>
  )
}

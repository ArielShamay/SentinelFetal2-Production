// src/components/detail/FindingsPanel.tsx
// Displays the 11 clinical feature flags for a single bed.

import React from 'react'
import type { BedData } from '../../stores/bedStore'

interface Props {
  bed: BedData
}

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex justify-between items-center py-0.5 border-b border-gray-100 last:border-0">
      <span className="text-xs text-gray-500">{label}</span>
      <span className="text-xs font-mono text-gray-800">{value}</span>
    </div>
  )
}

function Flag({ on }: { on: boolean }) {
  return <span className={on ? 'font-semibold text-gray-900' : 'text-gray-400'}>{on ? 'Yes' : 'No'}</span>
}

export const FindingsPanel: React.FC<Props> = ({ bed }) => (
  <section className="rounded border border-gray-200 p-3 bg-white">
    <h3 className="text-xs font-semibold uppercase tracking-wide text-gray-500 mb-2">Clinical Findings</h3>
    <Row label="Baseline (BPM)"         value={bed.baselineBpm.toFixed(1)} />
    <Row label="Tachycardia"            value={<Flag on={bed.isTachycardia} />} />
    <Row label="Bradycardia"            value={<Flag on={bed.isBradycardia} />} />
    <Row label="Variability (BPM)"      value={bed.variabilityAmplitudeBpm.toFixed(1)} />
    <Row label="Variability category"   value={bed.variabilityCategory} />
    <Row label="Late decelerations"     value={bed.nLateDecelerations} />
    <Row label="Variable decelerations" value={bed.nVariableDecelerations} />
    <Row label="Prolonged decelerations"value={bed.nProlongedDecelerations} />
    <Row label="Max decel depth (BPM)"  value={bed.maxDecelerationDepthBpm.toFixed(1)} />
    <Row label="Sinusoidal"             value={<Flag on={bed.sinusoidalDetected} />} />
    <Row label="Tachysystole"           value={<Flag on={bed.tachysystoleDetected} />} />
  </section>
)

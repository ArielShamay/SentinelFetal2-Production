// src/components/detail/RiskGauge.tsx
// Horizontal progress bar + numeric risk score + risk_delta arrow (§11.15).
// Rising risk (delta > 0.02): bold arrow up
// Falling risk (delta < -0.02): lighter arrow down
// Stable: → arrow

import React from 'react'

interface Props {
  riskScore: number    // 0..1
  riskDelta: number    // signed change since last window
  alert: boolean
}

function DeltaArrow({ delta }: { delta: number }) {
  if (delta > 0.02) return <span className="text-gray-900 font-bold">↑</span>
  if (delta < -0.02) return <span className="text-gray-400">↓</span>
  return <span className="text-gray-400">→</span>
}

export const RiskGauge: React.FC<Props> = ({ riskScore, riskDelta, alert }) => {
  const pct = Math.max(0, Math.min(100, Math.round(riskScore * 100)))

  return (
    <div className="flex flex-col gap-1">
      <div className="flex items-baseline gap-2">
        <span className={['text-4xl font-bold tabular-nums', alert ? 'text-gray-900' : 'text-gray-700'].join(' ')}>
          {pct}%
        </span>
        <span className="text-lg"><DeltaArrow delta={riskDelta} /></span>
        <span className="text-xs text-gray-500 ml-auto">risk score</span>
      </div>

      {/* B&W gradient bar */}
      <div className="w-full h-3 rounded bg-gray-100 overflow-hidden">
        <div
          className="h-full rounded transition-all duration-500"
          style={{
            width: `${pct}%`,
            background: 'linear-gradient(90deg, #d1d5db 0%, #374151 60%, #111827 100%)',
            backgroundSize: '200% 100%',
            backgroundPosition: `${100 - pct}% center`,
          }}
        />
      </div>
    </div>
  )
}

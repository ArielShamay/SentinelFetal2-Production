// src/components/ward/BedCard.tsx
// One bed tile in the ward grid.
// React.memo — only re-renders when riskScore / alert / isStale / warmup change.
// Risk bar is a B&W gradient (light → dark = low → high risk).

import React from 'react'
import type { BedData } from '../../stores/bedStore'
import { StatusBadge } from '../common/StatusBadge'
import { useStaleDetector } from '../../hooks/useStaleDetector'

interface Props {
  bed: BedData
  onClick: () => void
}

export const BedCard: React.FC<Props> = React.memo(({ bed, onClick }) => {
  const isStale = useStaleDetector(bed.lastUpdate)

  const riskPct   = Math.round(bed.riskScore * 100)
  const alertBorder = bed.alert ? 'border-2 border-gray-900' : 'border border-gray-200'

  return (
    <button
      className={[
        'relative flex flex-col gap-1 rounded-lg p-3 text-left bg-white shadow-sm',
        'hover:shadow-md transition-shadow cursor-pointer w-full',
        alertBorder,
        isStale ? 'opacity-60' : '',
      ].join(' ')}
      onClick={onClick}
    >
      {/* Header row */}
      <div className="flex items-center justify-between">
        <span className="text-sm font-mono font-semibold text-gray-900">
          Bed {bed.bedId}
        </span>
        <div className="flex items-center gap-1">
          {bed.warmup && <StatusBadge variant="warmup" />}
          {isStale && <StatusBadge variant="stale" />}
          {bed.alert && !isStale && <StatusBadge variant="alert" />}
          {!bed.alert && !isStale && !bed.warmup && <StatusBadge variant="live" />}
        </div>
      </div>

      {/* Risk score */}
      <div className="flex items-baseline gap-1.5">
        <span className={[
          'text-2xl font-bold tabular-nums',
          bed.alert ? 'text-gray-900' : 'text-gray-700',
        ].join(' ')}>
          {riskPct}%
        </span>
        <span className="text-xs text-gray-500">risk</span>
      </div>

      {/* Risk bar — B&W gradient (§8) */}
      <div className="w-full h-1.5 rounded bg-gray-100 overflow-hidden">
        <div
          className="h-full rounded transition-all duration-500"
          style={{
            width: `${riskPct}%`,
            background: `linear-gradient(90deg, #d1d5db 0%, #374151 60%, #111827 100%)`,
            backgroundSize: '200% 100%',
            backgroundPosition: `${100 - riskPct}% center`,
          }}
        />
      </div>

      {/* Recording ID */}
      <span className="text-xs text-gray-400 font-mono">
        {bed.recordingId}
      </span>
    </button>
  )
})

BedCard.displayName = 'BedCard'

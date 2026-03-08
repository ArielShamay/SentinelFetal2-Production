// src/components/detail/CTGChart.tsx
// Container div that hosts a lightweight-charts instance via useCTGChart.
// The chart updates come from chartUpdateBus — never through React state.

import React, { useRef } from 'react'
import { useCTGChart } from '../../hooks/useCTGChart'
import type { EventAnnotation } from '../../types'

interface Props {
  bedId: string
  activeEvents?: EventAnnotation[]
  baselineBpm?: number
  compact?: boolean
}

export const CTGChart: React.FC<Props> = ({ bedId, activeEvents, baselineBpm, compact }) => {
  const containerRef = useRef<HTMLDivElement>(null)
  useCTGChart(containerRef, bedId, activeEvents, baselineBpm, compact)

  return (
    <div
      ref={containerRef}
      className={`w-full rounded overflow-hidden bg-white ${compact ? 'h-28' : 'h-72 border border-gray-200'}`}
    />
  )
}

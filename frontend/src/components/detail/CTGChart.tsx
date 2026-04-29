// src/components/detail/CTGChart.tsx
// Container div that hosts a lightweight-charts instance via useCTGChart.
// Used exclusively in DetailView — full-size chart with axes, baseline, markers.
// Mini-strip in BedCard uses Sparkline (canvas-based) instead.

import React, { useRef } from 'react'
import { useCTGChart } from '../../hooks/useCTGChart'
import type { EventAnnotation } from '../../types'

interface Props {
  bedId: string
  activeEvents?: EventAnnotation[]
  baselineBpm?: number
}

export const CTGChart: React.FC<Props> = ({ bedId, activeEvents, baselineBpm }) => {
  const containerRef = useRef<HTMLDivElement>(null)
  useCTGChart(containerRef, bedId, activeEvents, baselineBpm)

  return (
    <div
      ref={containerRef}
      className="w-full h-72 rounded overflow-hidden bg-white border border-gray-200"
    />
  )
}

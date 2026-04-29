// src/components/detail/CTGChart.tsx
// Container div that hosts a lightweight-charts instance via useCTGChart.
// Used exclusively in DetailView — full-size chart with axes, baseline, markers.
// Mini-strip in BedCard uses Sparkline (canvas-based) instead.

import React, { useEffect, useRef } from 'react'
import type { IChartApi } from 'lightweight-charts'
import { useCTGChart } from '../../hooks/useCTGChart'
import type { DetectionEvent, EventAnnotation } from '../../types'
import { ChartOverlay } from './ChartOverlay'

interface Props {
  bedId: string
  activeEvents?: EventAnnotation[]
  baselineBpm?: number
  detectionHistory?: DetectionEvent[]
  onChartReady?: (chart: IChartApi | null) => void
}

export const CTGChart: React.FC<Props> = ({
  bedId,
  activeEvents,
  baselineBpm,
  detectionHistory = [],
  onChartReady,
}) => {
  const wrapperRef = useRef<HTMLDivElement>(null)
  const containerRef = useRef<HTMLDivElement>(null)
  const { chartApi } = useCTGChart(containerRef, bedId, activeEvents, baselineBpm, detectionHistory)

  useEffect(() => {
    onChartReady?.(chartApi)
  }, [chartApi, onChartReady])

  return (
    <div
      ref={wrapperRef}
      className="relative w-full h-72 rounded overflow-hidden bg-white border border-gray-200"
    >
      <div ref={containerRef} className="absolute inset-0" />
      <ChartOverlay events={detectionHistory} chartApi={chartApi} containerRef={wrapperRef} />
    </div>
  )
}

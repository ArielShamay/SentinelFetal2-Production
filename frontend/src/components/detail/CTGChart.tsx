// src/components/detail/CTGChart.tsx
// Container div that hosts a lightweight-charts instance via useCTGChart.
// The chart updates come from chartUpdateBus — never through React state.

import React, { useRef } from 'react'
import { useCTGChart } from '../../hooks/useCTGChart'

interface Props {
  bedId: string
}

export const CTGChart: React.FC<Props> = ({ bedId }) => {
  const containerRef = useRef<HTMLDivElement>(null)
  useCTGChart(containerRef, bedId)

  return (
    <div
      ref={containerRef}
      className="w-full h-72 rounded border border-gray-200 bg-white overflow-hidden"
    />
  )
}

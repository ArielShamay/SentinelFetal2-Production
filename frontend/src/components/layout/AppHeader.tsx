// src/components/layout/AppHeader.tsx
// Top bar: title, WS connection badge, bed count, simulation controls, fullscreen button.

import React, { useRef } from 'react'
import { useBedStore } from '../../stores/bedStore'
import { useFullscreen } from '../../hooks/useFullscreen'
import { StatusBadge } from '../common/StatusBadge'
import { SimulationControls } from '../common/SimulationControls'

export const AppHeader: React.FC = () => {
  const connected = useBedStore(s => s.connected)
  const bedCount  = useBedStore(s => s.beds.size)

  const pageRef = useRef<HTMLElement | null>(null)
  const { isFullscreen, toggleFullscreen } = useFullscreen(pageRef)

  // attach ref to document.body for full-page fullscreen
  React.useEffect(() => {
    pageRef.current = document.body as HTMLElement
  }, [])

  return (
    <header className="flex items-center justify-between gap-4 px-4 py-2 border-b border-gray-200 bg-white">
      {/* Left: title + status */}
      <div className="flex items-center gap-3">
        <h1 className="text-base font-semibold tracking-tight text-gray-900">
          SentinelFetal
        </h1>
        <StatusBadge variant={connected ? 'live' : 'disconnected'} />
        <span className="text-xs text-gray-500">{bedCount} beds</span>
      </div>

      {/* Centre: simulation controls */}
      <SimulationControls />

      {/* Right: fullscreen toggle */}
      <button
        className="p-1.5 rounded hover:bg-gray-100 text-gray-600 text-xs"
        onClick={toggleFullscreen}
        title={isFullscreen ? 'Exit fullscreen' : 'Fullscreen'}
      >
        {isFullscreen ? '⊠' : '⛶'}
      </button>
    </header>
  )
}

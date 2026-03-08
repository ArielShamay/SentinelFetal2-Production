// src/components/ward/WardView.tsx
// Main monitoring grid.  Beds are sorted by riskScore descending.
// Grid columns controlled by uiStore.gridColumns.
// Click → navigate to /bed/:id (DetailView).

import React, { useCallback, useMemo } from 'react'
import { useBedStore } from '../../stores/bedStore'
import { useUIStore } from '../../stores/uiStore'
import { BedCard } from './BedCard'

const GRID_COLS: Record<number, string> = {
  1: 'grid-cols-1',
  2: 'grid-cols-2',
  3: 'grid-cols-3',
  4: 'grid-cols-4',
}

export const WardView: React.FC = () => {
  const beds             = useBedStore(s => s.beds)
  const gridColumns      = useUIStore(s => s.gridColumns)
  const setSelectedBedId = useUIStore(s => s.setSelectedBedId)

  const sorted = useMemo(
    () => Array.from(beds.values()).sort((a, b) => b.riskScore - a.riskScore),
    [beds],
  )

  const handleClick = useCallback(
    (bedId: string) => setSelectedBedId(bedId),
    [setSelectedBedId],
  )

  const colClass = GRID_COLS[gridColumns] ?? 'grid-cols-2'

  if (sorted.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-full text-gray-400 select-none">
        <p className="text-sm">Waiting for data…</p>
        <p className="text-xs mt-1">Start the simulation or connect to the backend.</p>
      </div>
    )
  }

  return (
    <div className={`grid ${colClass} gap-3 p-4 auto-rows-fr`}>
      {sorted.map(bed => (
        <BedCard
          key={bed.bedId}
          bed={bed}
          onClick={handleClick}
        />
      ))}
    </div>
  )
}

// src/App.tsx
// Root component: opens WS stream, provides grid-column toolbar, routes to views.

import React, { useEffect, useState } from 'react'
import { Routes, Route } from 'react-router-dom'
import { useBedStream } from './hooks/useBedStream'
import { useBedStore } from './stores/bedStore'
import { useUIStore } from './stores/uiStore'
import { AppHeader } from './components/layout/AppHeader'
import { WardView } from './components/ward/WardView'
import { DetailView } from './components/detail/DetailView'

const GRID_OPTIONS = [1, 2, 3, 4]
const CONNECTION_LOST_THRESHOLD_S = 30

/** Full-screen overlay when WS heartbeat has been absent >30s — PLAN.md §11.4 */
function ConnectionLostBanner() {
  const lastHeartbeat = useBedStore(s => s.lastHeartbeat)
  const [lost, setLost] = useState(false)

  useEffect(() => {
    const id = setInterval(() => {
      // lastHeartbeat === 0 means we have never received a heartbeat yet (startup)
      if (lastHeartbeat === 0) { setLost(false); return }
      setLost(Date.now() / 1000 - lastHeartbeat > CONNECTION_LOST_THRESHOLD_S)
    }, 2000)
    return () => clearInterval(id)
  }, [lastHeartbeat])

  if (!lost) return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 pointer-events-none">
      <div className="bg-white border-2 border-gray-900 rounded-xl px-10 py-7 text-center shadow-2xl">
        <p className="text-2xl font-bold text-gray-900">⚠ CONNECTION LOST</p>
        <p className="text-sm text-gray-500 mt-2">Attempting to reconnect…</p>
      </div>
    </div>
  )
}

function GridSelector() {
  const gridColumns    = useUIStore(s => s.gridColumns)
  const setGridColumns = useUIStore(s => s.setGridColumns)
  return (
    <div className="flex items-center gap-1 px-4 py-1 border-b border-gray-100 bg-gray-50">
      <span className="text-xs text-gray-500 mr-1">Grid:</span>
      {GRID_OPTIONS.map(n => (
        <button
          key={n}
          className={[
            'px-2 py-0.5 text-xs rounded border transition-colors',
            gridColumns === n
              ? 'bg-gray-900 text-white border-gray-900'
              : 'bg-white text-gray-600 border-gray-200 hover:bg-gray-100',
          ].join(' ')}
          onClick={() => setGridColumns(n)}
        >
          {n}×{n}
        </button>
      ))}
    </div>
  )
}

export const App: React.FC = () => {
  useBedStream()

  return (
    <div className="flex flex-col h-full">
      <ConnectionLostBanner />
      <AppHeader />
      <GridSelector />
      <main className="flex-1 overflow-auto">
        <Routes>
          <Route path="/"        element={<WardView />} />
          <Route path="/bed/:id" element={<DetailView />} />
        </Routes>
      </main>
    </div>
  )
}

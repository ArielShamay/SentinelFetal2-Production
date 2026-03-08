// src/components/common/SimulationControls.tsx
// Start / Stop / Pause / Resume + speed selector.
// State is sourced from uiStore (reconciled from backend) rather than local state,
// so it stays accurate after failed requests or external changes.

import React, { useCallback, useEffect, useState } from 'react'
import { useUIStore } from '../../stores/uiStore'
import type { SimulationStatus } from '../../types'

const SPEEDS = [1, 2, 5, 10]

async function apiPost(path: string, body?: unknown): Promise<boolean> {
  try {
    const r = await fetch(path, {
      method: 'POST',
      headers: body ? { 'Content-Type': 'application/json' } : undefined,
      body: body ? JSON.stringify(body) : undefined,
    })
    return r.ok
  } catch {
    return false
  }
}

export const SimulationControls: React.FC = () => {
  const running    = useUIStore(s => s.simulationRunning)
  const paused     = useUIStore(s => s.simulationPaused)
  const setRunning = useUIStore(s => s.setSimulationRunning)
  const setPaused  = useUIStore(s => s.setSimulationPaused)
  const [bedCount, setBedCount] = useState(2)

  // Reconcile UI state with backend
  const refreshStatus = useCallback(async () => {
    try {
      const r = await fetch('/api/simulation/status')
      if (!r.ok) return
      const data = await r.json() as SimulationStatus
      setRunning(data.running)
      setPaused(data.paused)
    } catch { /* network unavailable — keep current UI state */ }
  }, [setRunning, setPaused])

  // Sync on mount
  useEffect(() => { void refreshStatus() }, [refreshStatus])

  async function handleStart() {
    const beds = Array.from({ length: bedCount }, (_, i) => ({
      bed_id: `bed_${String(i + 1).padStart(2, '0')}`,
      recording_id: null,
    }))
    await apiPost('/api/simulation/start', { beds })
    await refreshStatus()
  }

  async function handleStop() {
    await apiPost('/api/simulation/stop')
    await refreshStatus()
  }

  async function handlePauseResume() {
    const path = paused ? '/api/simulation/resume' : '/api/simulation/pause'
    await apiPost(path)
    await refreshStatus()
  }

  async function handleSpeed(s: number) {
    await apiPost('/api/simulation/speed', { speed: s })
  }

  const btnBase =
    'px-3 py-1 text-sm rounded border border-gray-300 hover:bg-gray-100 active:bg-gray-200 transition-colors disabled:opacity-40 disabled:cursor-not-allowed'

  return (
    <div className="flex items-center gap-2 flex-wrap">
      {!running && (
        <div className="flex items-center gap-1">
          <span className="text-xs text-gray-500">Beds:</span>
          <input
            type="number"
            min={1}
            max={16}
            value={bedCount}
            onChange={e => setBedCount(Math.min(16, Math.max(1, Number(e.target.value))))}
            className="w-12 text-sm border border-gray-300 rounded px-1 py-0.5 text-center"
          />
        </div>
      )}
      <button className={btnBase} onClick={handleStart} disabled={running && !paused}>
        ▶ Start
      </button>
      <button className={btnBase} onClick={handlePauseResume} disabled={!running}>
        {paused ? '▷ Resume' : '⏸ Pause'}
      </button>
      <button className={btnBase} onClick={handleStop} disabled={!running}>
        ⏹ Stop
      </button>

      <span className="text-gray-400 text-xs">|</span>

      {SPEEDS.map(s => (
        <button
          key={s}
          className={`${btnBase} font-mono`}
          onClick={() => handleSpeed(s)}
        >
          {s}×
        </button>
      ))}
    </div>
  )
}


// src/stores/uiStore.ts
// Global UI state: layout, speed, sound, simulation status, god-mode stub.

import { create } from 'zustand'
import { setMuted } from '../utils/alertSound'

interface UIStore {
  gridColumns: number          // 1 | 2 | 3 | 4  — grid is gridColumns×gridColumns
  selectedBedId: string | null
  speed: number                // 1.0 | 2.0 | 5.0 | 10.0
  soundMuted: boolean
  simulationRunning: boolean   // reconciled from /api/simulation/status
  simulationPaused: boolean    // reconciled from /api/simulation/status
  godModeUnlocked: boolean     // Phase 6 stub — toggled by passcode dialog
  godModePin: string           // Phase 6 stub — PIN entered by user

  setGridColumns: (n: number) => void
  setSelectedBedId: (id: string | null) => void
  setSpeed: (s: number) => void
  setSoundMuted: (v: boolean) => void
  setSimulationRunning: (v: boolean) => void
  setSimulationPaused: (v: boolean) => void
  setGodModeUnlocked: (v: boolean) => void
  setGodModePin: (pin: string) => void
}

export const useUIStore = create<UIStore>(set => ({
  gridColumns: 2,
  selectedBedId: null,
  speed: 1.0,
  soundMuted: false,
  simulationRunning: false,
  simulationPaused: false,
  godModeUnlocked: false,
  godModePin: '',

  setGridColumns: (n: number) => set({ gridColumns: n }),
  setSelectedBedId: (id: string | null) => set({ selectedBedId: id }),
  setSpeed: (s: number) => set({ speed: s }),
  setSoundMuted: (v: boolean) => {
    setMuted(v)
    set({ soundMuted: v })
  },
  setSimulationRunning: (v: boolean) => set({ simulationRunning: v }),
  setSimulationPaused:  (v: boolean) => set({ simulationPaused: v }),
  setGodModeUnlocked: (v: boolean) => set({ godModeUnlocked: v }),
  setGodModePin: (pin: string) => set({ godModePin: pin }),
}))

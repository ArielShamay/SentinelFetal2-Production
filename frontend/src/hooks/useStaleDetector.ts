// src/hooks/useStaleDetector.ts
// Polls every 2s and returns true when lastUpdate is more than threshold seconds ago.

import { useEffect, useState } from 'react'

const POLL_MS = 2_000
const DEFAULT_THRESHOLD_S = 15

export function useStaleDetector(
  lastUpdate: number,           // Unix seconds
  threshold = DEFAULT_THRESHOLD_S,
): boolean {
  const [stale, setStale] = useState(false)

  useEffect(() => {
    function check() {
      const age = Date.now() / 1000 - lastUpdate
      setStale(age > threshold)
    }

    check()   // immediate on mount / when lastUpdate changes
    const id = setInterval(check, POLL_MS)
    return () => clearInterval(id)
  }, [lastUpdate, threshold])

  return stale
}

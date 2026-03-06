// src/hooks/useFullscreen.ts
// Toggle fullscreen on a target element ref.

import { useCallback, useEffect, useState } from 'react'

export function useFullscreen(ref: React.RefObject<HTMLElement | null>) {
  const [isFullscreen, setIsFullscreen] = useState(false)

  useEffect(() => {
    function onChange() {
      setIsFullscreen(!!document.fullscreenElement)
    }
    document.addEventListener('fullscreenchange', onChange)
    return () => document.removeEventListener('fullscreenchange', onChange)
  }, [])

  const toggleFullscreen = useCallback(() => {
    if (!document.fullscreenElement) {
      ref.current?.requestFullscreen().catch(() => undefined)
    } else {
      document.exitFullscreen().catch(() => undefined)
    }
  }, [ref])

  return { isFullscreen, toggleFullscreen }
}

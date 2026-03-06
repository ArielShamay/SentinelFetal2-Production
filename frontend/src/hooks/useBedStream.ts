// src/hooks/useBedStream.ts
// React integration for the WebSocket stream.
// Delegates transport (connect/reconnect/backoff) to wsClient singleton.
// On each message it:
//   1. calls updateFromWebSocket() / initializeFromSnapshot() (Zustand → WardView)
//   2. calls chartUpdateBus.publish() (direct to CTG chart, bypassing React render — BUG-10)

import { useEffect } from 'react'
import { useBedStore } from '../stores/bedStore'
import { wsClient } from '../services/wsClient'
import { chartUpdateBus } from '../utils/chartUpdateBus'
import type { WSMessage } from '../types'

export function useBedStream(): void {
  const updateFromWebSocket  = useBedStore(s => s.updateFromWebSocket)
  const initializeFromSnapshot = useBedStore(s => s.initializeFromSnapshot)
  const setConnected = useBedStore(s => s.setConnected)
  const setHeartbeat = useBedStore(s => s.setHeartbeat)

  useEffect(() => {
    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:'
    const url = `${protocol}//${location.host}/ws/stream`

    const unsubStatus = wsClient.onStatus(setConnected)

    const unsubMsg = wsClient.onMessage((raw: string) => {
      let msg: WSMessage
      try {
        msg = JSON.parse(raw) as WSMessage
      } catch {
        return
      }

      if (msg.type === 'batch_update') {
        for (const u of msg.updates) {
          // tStart derived from stream elapsed_seconds so chart timestamps stay
          // monotonic at any replay speed — PLAN.md §11.2
          const tStart = u.elapsed_seconds - u.fhr_latest.length * 0.25
          updateFromWebSocket(u)
          chartUpdateBus.publish(u.bed_id, u.fhr_latest, u.uc_latest, tStart)
        }
      } else if (msg.type === 'initial_state') {
        initializeFromSnapshot(msg.beds)
      } else if (msg.type === 'heartbeat') {
        setHeartbeat(msg.ts)
      }
    })

    wsClient.connect(url)

    return () => {
      unsubStatus()
      unsubMsg()
      wsClient.disconnect()
    }
    // mount-once only; store selectors are stable Zustand actions
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])
}

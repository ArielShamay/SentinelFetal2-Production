// src/hooks/useBedStream.ts
// React integration for the WebSocket stream.
// Delegates transport (connect/reconnect/backoff) to wsClient singleton.
// On each message it:
//   1. calls updateFromWebSocket() / initializeFromSnapshot() (Zustand → WardView)
//   2. calls chartUpdateBus.publish() for each chart_tick (4 Hz raw samples, BUG-10)

import { useEffect } from 'react'
import { useBedStore } from '../stores/bedStore'
import { wsClient } from '../services/wsClient'
import { chartUpdateBus } from '../utils/chartUpdateBus'
import type { WSMessage } from '../types'

const CHART_TICKS_PER_CHUNK = 128

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
        // Inference updates — risk scores, clinical features, fhrRing/ucRing population
        for (const u of msg.updates) {
          updateFromWebSocket(u)
        }

        // Ward ticks (downsampled ≤ 4 Hz): publish to ward channel for Sparkline components.
        // These arrive for all beds at low rate — no chunking needed.
        const wardTicks = msg.ward_chart_ticks ?? []
        for (const tick of wardTicks) {
          chartUpdateBus.publishWard(tick.bed_id, tick.fhr, tick.uc, tick.t)
        }

        // Detail ticks (full-rate, focused bed only): chunk large reconnect bursts.
        const ticks = msg.chart_ticks ?? []
        for (let i = 0; i < ticks.length; i += CHART_TICKS_PER_CHUNK) {
          const chunk = ticks.slice(i, i + CHART_TICKS_PER_CHUNK)
          const publishChunk = () => {
            for (const tick of chunk) {
              chartUpdateBus.publish(tick.bed_id, [tick.fhr], [tick.uc], tick.t)
            }
          }
          if (i === 0) {
            publishChunk()
          } else {
            window.setTimeout(publishChunk, 0)
          }
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

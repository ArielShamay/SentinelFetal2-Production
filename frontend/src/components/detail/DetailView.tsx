// src/components/detail/DetailView.tsx
// Full-screen detail view for a single bed.
// Used both as a route (/bed/:id) and inside a modal (bedId prop + onClose callback).

import React, { useCallback, useEffect, useState } from 'react'
import type { IChartApi, Time } from 'lightweight-charts'
import { useParams, Link } from 'react-router-dom'
import { useBedStore } from '../../stores/bedStore'
import { useUIStore } from '../../stores/uiStore'
import { useStaleDetector } from '../../hooks/useStaleDetector'
import { StatusBadge } from '../common/StatusBadge'
import { RiskGauge } from './RiskGauge'
import { FindingsPanel } from './FindingsPanel'
import { AlertHistory } from './AlertHistory'
import { CTGChart } from './CTGChart'
import { DetectionList } from './DetectionList'
import { ExplanationPanel } from './ExplanationPanel'
import { GodModePanel } from '../god-mode/GodModePanel'
import { EventJournal } from '../god-mode/EventJournal'
import { wsClient } from '../../services/wsClient'
import type { DetectionEvent } from '../../types'

interface Props {
  bedId?: string
  onClose?: () => void
}

export const DetailView: React.FC<Props> = ({ bedId: propBedId, onClose }) => {
  const { id: routeId } = useParams<{ id: string }>()
  const id         = propBedId ?? routeId
  const bed        = useBedStore(s => id ? s.beds.get(id) : undefined)
  const isStale    = useStaleDetector(bed?.lastUpdate ?? 0)
  const godModePin = useUIStore(s => s.godModePin)
  const [chartApi, setChartApi] = useState<IChartApi | null>(null)

  // Notify backend that this client is focused on this bed so it receives
  // full-rate chart ticks for the detail chart (Ruba 2).
  useEffect(() => {
    if (id) {
      wsClient.send(JSON.stringify({ type: 'focus', bed_id: id }))
    }
    return () => {
      wsClient.send(JSON.stringify({ type: 'unfocus' }))
    }
  }, [id])

  if (!bed) {
    return (
      <div className="flex flex-col items-center justify-center h-full gap-3 text-gray-400">
        <p className="text-sm">Bed "{id}" not found.</p>
        {onClose
          ? <button onClick={onClose} className="text-xs underline">← Back to ward</button>
          : <Link to="/" className="text-xs underline">← Back to ward</Link>
        }
      </div>
    )
  }

  const elapsed = bed.elapsedSeconds
  const mm = Math.floor(elapsed / 60).toString().padStart(2, '0')
  const ss = Math.floor(elapsed % 60).toString().padStart(2, '0')

  const focusOnEvent = useCallback((event: DetectionEvent) => {
    const chart = chartApi
    if (!chart) return
    const from = Math.max(0, event.start_sample / 4.0 - 60)
    const endSample = event.end_sample ?? event.start_sample
    const to = Math.max(from + 30, endSample / 4.0 + 60)
    chart.timeScale().setVisibleRange({ from: from as Time, to: to as Time })
  }, [chartApi])

  return (
    <div className={['flex flex-col gap-4 p-4', isStale ? 'opacity-80' : ''].join(' ')}>
      {/* Back + header */}
      <div className="flex items-center gap-3">
        {onClose
          ? <button onClick={onClose} className="text-xs text-gray-500 hover:text-gray-800 underline">← Ward</button>
          : <Link to="/" className="text-xs text-gray-500 hover:text-gray-800 underline">← Ward</Link>
        }
        <h2 className="text-base font-semibold text-gray-900">Bed {bed.bedId}</h2>
        <span className="text-xs font-mono text-gray-400">{bed.recordingId}</span>

        <div className="ml-auto flex items-center gap-2">
          {bed.warmup && <StatusBadge variant="warmup" />}
          {isStale   && <StatusBadge variant="stale" />}
          {bed.alert  && <StatusBadge variant="alert" />}
          {!bed.alert && !isStale && !bed.warmup && <StatusBadge variant="live" />}
          <span className="text-xs font-mono text-gray-500">{mm}:{ss}</span>
        </div>
      </div>

      {/* Risk gauge */}
      <div className="rounded border border-gray-200 p-4 bg-white">
        <RiskGauge
          riskScore={bed.riskScore}
          riskDelta={bed.riskDelta}
          alert={bed.alert}
          topContribution={bed.topContributions[0]}
        />
      </div>

      {/* God Mode panel */}
      <GodModePanel bedId={bed.bedId} />

      {/* CTG chart — detectionHistory drives persistent explainability overlays */}
      <CTGChart
        bedId={bed.bedId}
        activeEvents={bed.activeEvents}
        baselineBpm={bed.baselineBpm}
        detectionHistory={bed.detectionHistory}
        onChartReady={setChartApi}
      />

      {/* Lower panels */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <FindingsPanel bed={bed} topContributions={bed.topContributions} />
        <ExplanationPanel topContributions={bed.topContributions} warmup={bed.warmup} />
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <DetectionList events={bed.detectionHistory} onSelect={focusOnEvent} />
        <AlertHistory bedId={bed.bedId} />
      </div>

      {/* Event journal — visible only after PIN unlock */}
      <EventJournal bedId={bed.bedId} pin={godModePin} />
    </div>
  )
}

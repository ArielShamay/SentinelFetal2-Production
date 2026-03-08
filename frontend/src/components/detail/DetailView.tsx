// src/components/detail/DetailView.tsx
// Full-screen detail page for a single bed.
// Route: /bed/:id

import React from 'react'
import { useParams, Link } from 'react-router-dom'
import { useBedStore } from '../../stores/bedStore'
import { useUIStore } from '../../stores/uiStore'
import { useStaleDetector } from '../../hooks/useStaleDetector'
import { StatusBadge } from '../common/StatusBadge'
import { RiskGauge } from './RiskGauge'
import { FindingsPanel } from './FindingsPanel'
import { AlertHistory } from './AlertHistory'
import { CTGChart } from './CTGChart'
import { GodModePanel } from '../god-mode/GodModePanel'
import { EventJournal } from '../god-mode/EventJournal'

export const DetailView: React.FC = () => {
  const { id } = useParams<{ id: string }>()
  const bed        = useBedStore(s => id ? s.beds.get(id) : undefined)
  const isStale    = useStaleDetector(bed?.lastUpdate ?? 0)
  const godModePin = useUIStore(s => s.godModePin)

  if (!bed) {
    return (
      <div className="flex flex-col items-center justify-center h-full gap-3 text-gray-400">
        <p className="text-sm">Bed "{id}" not found.</p>
        <Link to="/" className="text-xs underline">← Back to ward</Link>
      </div>
    )
  }

  const elapsed = bed.elapsedSeconds
  const mm = Math.floor(elapsed / 60).toString().padStart(2, '0')
  const ss = Math.floor(elapsed % 60).toString().padStart(2, '0')

  return (
    <div className={['flex flex-col gap-4 p-4', isStale ? 'opacity-80' : ''].join(' ')}>
      {/* Back + header */}
      <div className="flex items-center gap-3">
        <Link to="/" className="text-xs text-gray-500 hover:text-gray-800 underline">
          ← Ward
        </Link>
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
        />
      </div>

      {/* God Mode panel */}
      <GodModePanel bedId={bed.bedId} />

      {/* CTG chart — activeEvents drive timeline markers, baselineBpm draws reference line */}
      <CTGChart bedId={bed.bedId} activeEvents={bed.activeEvents} baselineBpm={bed.baselineBpm} />

      {/* Lower panels */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <FindingsPanel bed={bed} />
        <AlertHistory bedId={bed.bedId} />
      </div>

      {/* Event journal — visible only after PIN unlock */}
      <EventJournal bedId={bed.bedId} pin={godModePin} />
    </div>
  )
}

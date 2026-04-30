// src/components/common/Sparkline.tsx
// Lightweight canvas-based CTG mini-strip for ward bed cards.
//
// Mirrors the Detail chart's visual model without creating a chart instance:
// two time-aligned panes, adaptive Y ranges, baseline, alert coloring, and
// persistent event shading from detectionHistory.

import React, { useRef, useEffect } from 'react'
import { chartUpdateBus } from '../../utils/chartUpdateBus'
import type { DetectionEvent } from '../../types'

// Up to 240 ward ticks = 60 s at 4 Hz, or ~4 min at 1 Hz
const BUFFER_SIZE = 240
const COLOR_FHR   = '#111827'
const COLOR_UC    = '#6b7280'
const COLOR_GRID  = 'rgba(0,0,0,0.05)'
const COLOR_ALERT = '#dc2626'
const DECEL_EVENTS = new Set(['late_deceleration', 'variable_deceleration', 'prolonged_deceleration'])
const SLOW_STATE_EVENTS = new Set(['bradycardia', 'tachycardia', 'low_variability', 'sinusoidal', 'tachysystole'])

interface TickRecord {
  fhr: number
  uc: number
  t: number
}

interface Props {
  bedId: string
  detectionHistory: DetectionEvent[]
  baselineBpm?: number
}

function computeRange(values: number[], minSpan: number): { min: number; max: number } {
  if (values.length === 0) return { min: 0, max: minSpan }
  let min = Infinity
  let max = -Infinity
  for (const v of values) {
    if (!Number.isFinite(v)) continue
    if (v < min) min = v
    if (v > max) max = v
  }
  if (!Number.isFinite(min) || !Number.isFinite(max)) return { min: 0, max: minSpan }
  const mid = (min + max) / 2
  const span = Math.max(max - min, minSpan)
  const pad = span * 0.05
  return { min: mid - span / 2 - pad, max: mid + span / 2 + pad }
}

function inEventRange(timeSec: number, event: DetectionEvent): boolean {
  const startT = event.start_sample / 4.0
  const endT = event.end_sample !== null ? event.end_sample / 4.0 : Infinity
  return timeSec >= startT && timeSec <= endT
}

function getPointColor(timeSec: number, events: DetectionEvent[]): string {
  return events.some(event => inEventRange(timeSec, event)) ? COLOR_ALERT : COLOR_FHR
}

export const Sparkline: React.FC<Props> = ({ bedId, detectionHistory, baselineBpm }) => {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const buf        = useRef<TickRecord[]>([])
  const dirty     = useRef(false)
  const eventsRef = useRef(detectionHistory)
  const baselineRef = useRef(baselineBpm)
  eventsRef.current = detectionHistory
  baselineRef.current = baselineBpm

  useEffect(() => {
    dirty.current = true
  }, [detectionHistory, baselineBpm])

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return

    const syncCanvasSize = () => {
      const dpr = window.devicePixelRatio || 1
      const width = canvas.clientWidth || 200
      const height = canvas.clientHeight || 56
      canvas.width = Math.max(1, Math.round(width * dpr))
      canvas.height = Math.max(1, Math.round(height * dpr))
      const ctx = canvas.getContext('2d')
      if (ctx) ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    }

    syncCanvasSize()

    // Seed from ward history for immediate context on mount / page-refresh
    const hist = chartUpdateBus.getWardHistory(bedId)
    if (hist) {
      const step = 0.25
      const fhrVals = hist.fhrVals.slice(-BUFFER_SIZE)
      const ucVals = hist.ucVals.slice(-BUFFER_SIZE)
      const tStart = hist.tStart + Math.max(0, hist.fhrVals.length - fhrVals.length) * step
      buf.current = fhrVals.map((fhr, i) => ({ fhr, uc: ucVals[i] ?? 0, t: tStart + i * step }))
      dirty.current = true
    }

    // Subscribe to live ward ticks
    const unsub = chartUpdateBus.subscribeWard(bedId, (fhrVals, ucVals, tStart) => {
      const step = 0.25
      for (let i = 0; i < fhrVals.length; i++) {
        buf.current.push({ fhr: fhrVals[i], uc: ucVals[i] ?? 0, t: tStart + i * step })
      }
      // Trim with hysteresis to avoid allocating on every tick
      if (buf.current.length > BUFFER_SIZE + 20) buf.current = buf.current.slice(-BUFFER_SIZE)
      dirty.current = true
    })

    const xForTime = (t: number, t0: number, t1: number, w: number) => {
      if (t1 <= t0) return 0
      return ((t - t0) / (t1 - t0)) * w
    }

    const yForValue = (value: number, min: number, max: number, yTop: number, yBot: number) => {
      const norm = Math.max(0, Math.min(1, (value - min) / (max - min)))
      return yTop + (1 - norm) * (yBot - yTop)
    }

    const drawGrid = (ctx: CanvasRenderingContext2D, yTop: number, yBot: number, w: number) => {
      ctx.save()
      ctx.strokeStyle = COLOR_GRID
      ctx.lineWidth = 1
      ctx.setLineDash([1, 4])
      for (let i = 1; i <= 3; i++) {
        const y = yTop + ((yBot - yTop) * i) / 4
        ctx.beginPath()
        ctx.moveTo(0, y)
        ctx.lineTo(w, y)
        ctx.stroke()
      }
      ctx.restore()
    }

    const drawHatching = (
      ctx: CanvasRenderingContext2D,
      x1: number,
      x2: number,
      h: number,
    ) => {
      ctx.save()
      ctx.beginPath()
      ctx.rect(x1, 0, x2 - x1, h)
      ctx.clip()
      ctx.strokeStyle = 'rgba(220,38,38,0.30)'
      ctx.lineWidth = 1
      for (let x = x1 - h; x < x2 + 10; x += 10) {
        ctx.beginPath()
        ctx.moveTo(x, h)
        ctx.lineTo(x + h, 0)
        ctx.stroke()
      }
      ctx.restore()
    }

    const drawDotted = (
      ctx: CanvasRenderingContext2D,
      x1: number,
      x2: number,
      h: number,
    ) => {
      ctx.save()
      ctx.strokeStyle = 'rgba(220,38,38,0.24)'
      ctx.lineWidth = 1
      ctx.setLineDash([1, 5])
      for (let x = x1; x <= x2; x += 7) {
        ctx.beginPath()
        ctx.moveTo(x, 0)
        ctx.lineTo(x, h)
        ctx.stroke()
      }
      ctx.restore()
    }

    const drawEventShading = (
      ctx: CanvasRenderingContext2D,
      events: DetectionEvent[],
      t0: number,
      t1: number,
      w: number,
      h: number,
    ) => {
      for (const event of events) {
        const eventStart = event.start_sample / 4.0
        const eventEnd = event.still_ongoing || event.end_sample === null ? t1 : event.end_sample / 4.0
        if (eventEnd < t0 || eventStart > t1) continue

        const x1 = Math.max(0, Math.min(w, xForTime(eventStart, t0, t1, w)))
        const x2 = Math.max(0, Math.min(w, xForTime(eventEnd, t0, t1, w)))
        if (x2 <= x1) continue

        if (event.event_type === 'lr_high_risk') {
          ctx.fillStyle = 'rgba(220,38,38,0.10)'
          ctx.fillRect(x1, 0, x2 - x1, h)
          ctx.strokeStyle = 'rgba(220,38,38,0.35)'
          ctx.lineWidth = 1
          ctx.strokeRect(x1, 0, x2 - x1, h)
        } else if (DECEL_EVENTS.has(event.event_type)) {
          ctx.fillStyle = 'rgba(220,38,38,0.07)'
          ctx.fillRect(x1, 0, x2 - x1, h)
          drawHatching(ctx, x1, x2, h)
        } else if (SLOW_STATE_EVENTS.has(event.event_type)) {
          ctx.fillStyle = 'rgba(220,38,38,0.05)'
          ctx.fillRect(x1, 0, x2 - x1, h)
          drawDotted(ctx, x1, x2, h)
        }
      }
    }

    const drawLine = (
      ctx: CanvasRenderingContext2D,
      points: TickRecord[],
      valueOf: (p: TickRecord) => number,
      range: { min: number; max: number },
      yTop: number,
      yBot: number,
      t0: number,
      t1: number,
      w: number,
      colorOf: (p: TickRecord) => string,
    ) => {
      if (points.length < 2) return

      let currentColor = colorOf(points[0])
      ctx.beginPath()
      ctx.strokeStyle = currentColor
      ctx.lineWidth = 1.25

      const first = points[0]
      ctx.moveTo(xForTime(first.t, t0, t1, w), yForValue(valueOf(first), range.min, range.max, yTop, yBot))

      for (let i = 1; i < points.length; i++) {
        const point = points[i]
        const nextColor = colorOf(point)
        const x = xForTime(point.t, t0, t1, w)
        const y = yForValue(valueOf(point), range.min, range.max, yTop, yBot)

        if (nextColor !== currentColor) {
          ctx.stroke()
          ctx.beginPath()
          const prev = points[i - 1]
          ctx.strokeStyle = nextColor
          ctx.moveTo(xForTime(prev.t, t0, t1, w), yForValue(valueOf(prev), range.min, range.max, yTop, yBot))
          currentColor = nextColor
        }

        ctx.lineTo(x, y)
      }
      ctx.stroke()
    }

    // RAF loop — redraws only when dirty
    let rafHandle = requestAnimationFrame(function draw() {
      rafHandle = requestAnimationFrame(draw)
      if (!dirty.current) return
      dirty.current = false

      const ctx = canvas.getContext('2d')
      if (!ctx) return

      const dpr = window.devicePixelRatio || 1
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)

      const w = canvas.clientWidth || 200
      const h = canvas.clientHeight || 56
      const points = buf.current.slice(-BUFFER_SIZE)
      if (points.length < 2) {
        ctx.clearRect(0, 0, w, h)
        return
      }

      const t0 = points[0].t
      const t1 = points[points.length - 1].t
      const events = eventsRef.current.filter(event => {
        const start = event.start_sample / 4.0
        const end = event.end_sample !== null ? event.end_sample / 4.0 : t1
        return end >= t0 && start <= t1
      })

      ctx.clearRect(0, 0, w, h)
      drawEventShading(ctx, events, t0, t1, w, h)

      const fhrPane = { top: h * 0.05, bot: h * 0.45 }
      const ucPane = { top: h * 0.55, bot: h * 0.95 }
      const baseline = baselineRef.current
      const fhrValues = baseline && baseline > 50
        ? [...points.map(p => p.fhr), baseline]
        : points.map(p => p.fhr)
      const fhrRange = computeRange(fhrValues, 30)
      const ucRange = computeRange(points.map(p => p.uc), 20)

      drawGrid(ctx, fhrPane.top, fhrPane.bot, w)
      drawGrid(ctx, ucPane.top, ucPane.bot, w)

      if (baseline && baseline > 50) {
        const y = yForValue(baseline, fhrRange.min, fhrRange.max, fhrPane.top, fhrPane.bot)
        ctx.save()
        ctx.strokeStyle = COLOR_UC
        ctx.lineWidth = 1
        ctx.setLineDash([2, 4])
        ctx.beginPath()
        ctx.moveTo(0, y)
        ctx.lineTo(w, y)
        ctx.stroke()
        ctx.restore()
      }

      drawLine(ctx, points, p => p.fhr, fhrRange, fhrPane.top, fhrPane.bot, t0, t1, w, p => getPointColor(p.t, events))
      drawLine(ctx, points, p => p.uc,  ucRange,  ucPane.top,  ucPane.bot,  t0, t1, w, () => COLOR_UC)
    })

    // ResizeObserver — keeps canvas pixel dimensions in sync with CSS layout
    const ro = new ResizeObserver(() => {
      syncCanvasSize()
      dirty.current = true
    })
    ro.observe(canvas)

    return () => {
      unsub()
      cancelAnimationFrame(rafHandle)
      ro.disconnect()
    }
  }, [bedId])

  return (
    <canvas
      ref={canvasRef}
      style={{ width: '100%', height: '100%', display: 'block' }}
    />
  )
}

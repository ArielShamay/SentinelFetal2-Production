// src/components/detail/ChartOverlay.tsx
// Canvas overlay for persistent explainability highlights on top of CTGChart.

import React, { useEffect, useRef } from 'react'
import type { IChartApi, Time } from 'lightweight-charts'
import type { DetectionEvent } from '../../types'

interface Props {
  events: DetectionEvent[]
  chartApi: IChartApi | null
  containerRef: React.RefObject<HTMLDivElement>
}

const DECEL_EVENTS = new Set(['late_deceleration', 'variable_deceleration', 'prolonged_deceleration'])
const SLOW_STATE_EVENTS = new Set(['bradycardia', 'tachycardia', 'low_variability', 'sinusoidal', 'tachysystole'])

function xForSample(chartApi: IChartApi, sample: number): number | null {
  const x = chartApi.timeScale().timeToCoordinate((sample / 4.0) as Time)
  return typeof x === 'number' ? x : null
}

function drawHatching(
  ctx: CanvasRenderingContext2D,
  x1: number,
  y1: number,
  x2: number,
  y2: number,
  spacing = 8,
): void {
  ctx.save()
  ctx.beginPath()
  ctx.rect(x1, y1, x2 - x1, y2 - y1)
  ctx.clip()
  ctx.strokeStyle = 'rgba(0,0,0,0.22)'
  ctx.lineWidth = 1
  for (let x = x1 - (y2 - y1); x < x2 + spacing; x += spacing) {
    ctx.beginPath()
    ctx.moveTo(x, y2)
    ctx.lineTo(x + (y2 - y1), y1)
    ctx.stroke()
  }
  ctx.restore()
}

function drawDottedLines(
  ctx: CanvasRenderingContext2D,
  x1: number,
  y1: number,
  x2: number,
  y2: number,
): void {
  ctx.save()
  ctx.strokeStyle = 'rgba(0,0,0,0.20)'
  ctx.lineWidth = 1
  ctx.setLineDash([1, 5])
  for (let x = x1; x <= x2; x += 6) {
    ctx.beginPath()
    ctx.moveTo(x, y1)
    ctx.lineTo(x, y2)
    ctx.stroke()
  }
  ctx.restore()
}

export const ChartOverlay: React.FC<Props> = ({ events, chartApi, containerRef }) => {
  const canvasRef = useRef<HTMLCanvasElement>(null)

  useEffect(() => {
    const canvas = canvasRef.current
    const container = containerRef.current
    if (!canvas || !container || !chartApi) return

    const syncSize = () => {
      const dpr = window.devicePixelRatio || 1
      const width = Math.max(1, container.clientWidth)
      const height = Math.max(1, container.clientHeight)
      canvas.width = Math.round(width * dpr)
      canvas.height = Math.round(height * dpr)
      canvas.style.width = `${width}px`
      canvas.style.height = `${height}px`
      const ctx = canvas.getContext('2d')
      if (ctx) ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    }

    const redraw = () => {
      syncSize()
      const ctx = canvas.getContext('2d')
      if (!ctx) return

      const w = container.clientWidth
      const h = container.clientHeight
      ctx.clearRect(0, 0, w, h)

      for (const event of events) {
        const xStartRaw = xForSample(chartApi, event.start_sample)
        const xEndRaw = event.still_ongoing || event.end_sample === null
          ? w
          : xForSample(chartApi, event.end_sample)

        if (xStartRaw === null && xEndRaw === null) continue

        const xStart = Math.max(0, Math.min(w, xStartRaw ?? 0))
        const xEnd = Math.max(0, Math.min(w, xEndRaw ?? w))
        if (xEnd <= 0 || xStart >= w || xEnd <= xStart) continue

        if (event.event_type === 'lr_high_risk') {
          ctx.fillStyle = 'rgba(0,0,0,0.10)'
          ctx.fillRect(xStart, 0, xEnd - xStart, h)
          ctx.strokeStyle = 'rgba(0,0,0,0.45)'
          ctx.lineWidth = 2
          ctx.strokeRect(xStart, 0, xEnd - xStart, h)
        } else if (DECEL_EVENTS.has(event.event_type)) {
          ctx.fillStyle = 'rgba(0,0,0,0.06)'
          ctx.fillRect(xStart, 0, xEnd - xStart, h)
          drawHatching(ctx, xStart, 0, xEnd, h)
        } else if (SLOW_STATE_EVENTS.has(event.event_type)) {
          ctx.fillStyle = 'rgba(0,0,0,0.05)'
          ctx.fillRect(xStart, 0, xEnd - xStart, h)
          drawDottedLines(ctx, xStart, 0, xEnd, h)
        }

        if (event.still_ongoing) {
          ctx.save()
          ctx.strokeStyle = 'rgba(0,0,0,0.55)'
          ctx.lineWidth = 1
          ctx.setLineDash([4, 4])
          ctx.beginPath()
          ctx.moveTo(xEnd, 0)
          ctx.lineTo(xEnd, h)
          ctx.stroke()
          ctx.restore()
        }

        if (xEnd - xStart >= 60) {
          ctx.fillStyle = 'rgba(17,24,39,0.85)'
          ctx.font = '10px sans-serif'
          ctx.fillText(event.description.slice(0, 30), xStart + 4, 12)
        }
      }
    }

    const ro = new ResizeObserver(redraw)
    ro.observe(container)
    chartApi.timeScale().subscribeVisibleTimeRangeChange(redraw)
    redraw()

    return () => {
      ro.disconnect()
      chartApi.timeScale().unsubscribeVisibleTimeRangeChange(redraw)
    }
  }, [chartApi, containerRef, events])

  return (
    <canvas
      ref={canvasRef}
      className="absolute inset-0 pointer-events-none z-10"
      aria-hidden="true"
    />
  )
}

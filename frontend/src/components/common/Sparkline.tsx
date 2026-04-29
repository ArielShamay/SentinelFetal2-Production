// src/components/common/Sparkline.tsx
// Lightweight canvas-based CTG mini-strip for ward bed cards.
//
// Subscribes to the WARD channel (≤ 4 Hz, downsampled) of chartUpdateBus.
// Uses a requestAnimationFrame loop with a dirty flag — only redraws when
// new data has arrived, so idle beds cost virtually nothing.
//
// No lightweight-charts — just 2D canvas lines.
// FHR (dark) drawn in top half; UC (grey) drawn in bottom half.

import React, { useRef, useEffect } from 'react'
import { chartUpdateBus } from '../../utils/chartUpdateBus'

// Up to 240 ward ticks = 60 s at 4 Hz, or ~4 min at 1 Hz
const BUFFER_SIZE = 240
const FHR_MIN = 50,  FHR_MAX = 210   // BPM display range
const UC_MIN  = 0,   UC_MAX  = 100   // mmHg display range

interface Props {
  bedId: string
}

export const Sparkline: React.FC<Props> = ({ bedId }) => {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const fhrBuf    = useRef<number[]>([])
  const ucBuf     = useRef<number[]>([])
  const dirty     = useRef(false)

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return

    // Initial size (ResizeObserver will refine it)
    canvas.width  = canvas.clientWidth  || 200
    canvas.height = canvas.clientHeight || 56

    // Seed from ward history for immediate context on mount / page-refresh
    const hist = chartUpdateBus.getWardHistory(bedId)
    if (hist) {
      fhrBuf.current = hist.fhrVals.slice(-BUFFER_SIZE)
      ucBuf.current  = hist.ucVals.slice(-BUFFER_SIZE)
      dirty.current  = true
    }

    // Subscribe to live ward ticks
    const unsub = chartUpdateBus.subscribeWard(bedId, (fhrVals, ucVals) => {
      for (const v of fhrVals) fhrBuf.current.push(v)
      for (const v of ucVals)  ucBuf.current.push(v)
      // Trim with hysteresis to avoid allocating on every tick
      if (fhrBuf.current.length > BUFFER_SIZE + 20) fhrBuf.current = fhrBuf.current.slice(-BUFFER_SIZE)
      if (ucBuf.current.length  > BUFFER_SIZE + 20) ucBuf.current  = ucBuf.current.slice(-BUFFER_SIZE)
      dirty.current = true
    })

    // Draw helper: renders a normalised line in a horizontal band of the canvas
    const drawLine = (
      ctx: CanvasRenderingContext2D,
      vals: number[],
      min: number, max: number,
      yTop: number, yBot: number,
      color: string,
    ) => {
      if (vals.length < 2) return
      ctx.beginPath()
      ctx.strokeStyle = color
      ctx.lineWidth   = 1
      const last = vals.length - 1
      const w    = ctx.canvas.width
      for (let i = 0; i <= last; i++) {
        const x    = (i / last) * w
        const norm = Math.max(0, Math.min(1, (vals[i] - min) / (max - min)))
        const y    = yTop + (1 - norm) * (yBot - yTop)
        if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y)
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

      const w    = canvas.width
      const h    = canvas.height
      const midY = Math.floor(h / 2)

      ctx.clearRect(0, 0, w, h)
      drawLine(ctx, fhrBuf.current, FHR_MIN, FHR_MAX, 1,        midY - 2, '#111827')
      drawLine(ctx, ucBuf.current,  UC_MIN,  UC_MAX,  midY + 2, h - 1,    '#6b7280')
    })

    // ResizeObserver — keeps canvas pixel dimensions in sync with CSS layout
    const ro = new ResizeObserver(() => {
      canvas.width  = canvas.clientWidth
      canvas.height = canvas.clientHeight
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

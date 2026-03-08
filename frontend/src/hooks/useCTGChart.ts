// src/hooks/useCTGChart.ts
// Creates a lightweight-charts instance in the provided container ref.
// Two panes: FHR (top, right axis) and UC (bottom, left axis).
// Subscribes to chartUpdateBus and calls series.update() — NEVER setData().
// BUG-10: chart updates come from the bus, completely decoupled from React render.

import { useEffect, useRef } from 'react'
import { createChart, ColorType, LineStyle } from 'lightweight-charts'
import type { IChartApi, ISeriesApi, IPriceLine, Time } from 'lightweight-charts'
import { chartUpdateBus } from '../utils/chartUpdateBus'
import type { EventAnnotation } from '../types'

// B&W palette (PLAN.md §8)
const COLOR_FHR  = '#111827'
const COLOR_UC   = '#6b7280'
const COLOR_BG   = '#ffffff'
const COLOR_GRID = '#e5e7eb'

export function useCTGChart(
  containerRef: React.RefObject<HTMLElement | null>,
  bedId: string,
  activeEvents?: EventAnnotation[],
  baselineBpm?: number,
  compact?: boolean,
) {
  const chartRef      = useRef<IChartApi | null>(null)
  const fhrSeries     = useRef<ISeriesApi<'Line'> | null>(null)
  const ucSeries      = useRef<ISeriesApi<'Line'> | null>(null)
  const baselineLine  = useRef<IPriceLine | null>(null)

  // Build time counter — each sample is spaced 1/4 s apart (4 Hz)
  const nextTimeFHR = useRef<number>(Math.floor(Date.now() / 1000))
  const nextTimeUC  = useRef<number>(Math.floor(Date.now() / 1000))

  // ── Create chart once ──────────────────────────────────────────
  useEffect(() => {
    const container = containerRef.current
    if (!container) return

    const chart = createChart(container, {
      width: container.clientWidth,
      height: container.clientHeight,
      layout: {
        background: { type: ColorType.Solid, color: COLOR_BG },
        textColor: COLOR_FHR,
      },
      grid: compact
        ? { vertLines: { visible: false }, horzLines: { visible: false } }
        : { vertLines: { color: COLOR_GRID, style: LineStyle.Dotted }, horzLines: { color: COLOR_GRID, style: LineStyle.Dotted } },
      rightPriceScale: compact ? { visible: false } : { visible: true, borderColor: COLOR_GRID },
      leftPriceScale: compact ? { visible: false } : { visible: true, borderColor: COLOR_GRID },
      timeScale: compact
        ? { visible: false }
        : { borderColor: COLOR_GRID, timeVisible: true, secondsVisible: false },
      crosshair: { mode: 0 },
    })
    chartRef.current = chart

    // FHR — upper portion, right axis
    const fhr = chart.addLineSeries({
      color: COLOR_FHR,
      lineWidth: 1,
      priceScaleId: 'right',
      priceFormat: { type: 'price', precision: 0, minMove: 1 },
      title: 'FHR',
    })
    chart.priceScale('right').applyOptions({ scaleMargins: { top: 0.05, bottom: 0.55 } })
    fhrSeries.current = fhr

    // UC — lower portion, left axis
    const uc = chart.addLineSeries({
      color: COLOR_UC,
      lineWidth: 1,
      priceScaleId: 'left',
      priceFormat: { type: 'price', precision: 0, minMove: 1 },
      title: 'UC',
    })
    chart.priceScale('left').applyOptions({ scaleMargins: { top: 0.55, bottom: 0.05 } })
    ucSeries.current = uc

    // Resize observer
    const ro = new ResizeObserver(() => {
      chart.resize(container.clientWidth, container.clientHeight)
    })
    ro.observe(container)

    return () => {
      ro.disconnect()
      chart.remove()
      chartRef.current   = null
      fhrSeries.current  = null
      ucSeries.current   = null
      baselineLine.current = null
    }
  }, [containerRef, compact])   // re-create if container or compact mode changes

  // ── Load history FIRST, then subscribe for live ticks ──
  // History is loaded synchronously via setData() BEFORE subscribing,
  // so live ticks (which arrive via update()) always have t > history end.
  // This eliminates the race condition where deferred setData() overwrites
  // live points that arrived between subscribe and setData.
  // Compact mini-charts skip history entirely (no visual value at 112px).
  useEffect(() => {
    if (!bedId) return

    const fhr = fhrSeries.current
    const uc  = ucSeries.current

    // Load history FIRST (full mode only, ~5ms for 4800 points)
    if (!compact && fhr && uc) {
      const hist = chartUpdateBus.getHistory(bedId)
      if (hist) {
        const step = 0.25
        try {
          fhr.setData(hist.fhrVals.map((v, i) => ({ time: (hist.tStart + i * step) as Time, value: v })))
          uc.setData(hist.ucVals.map((v, i) => ({ time: (hist.tStart + i * step) as Time, value: v })))
        } catch { /* ignore if chart was removed */ }
      }
    }

    // THEN subscribe for live ticks — all future ticks have t > history end
    const unsubscribe = chartUpdateBus.subscribe(bedId, (fhrVals, ucVals, tStart) => {
      const fhrS = fhrSeries.current
      const ucS  = ucSeries.current
      if (!fhrS || !ucS) return

      const step = 0.25
      for (let i = 0; i < fhrVals.length; i++) {
        const t = (tStart + i * step) as Time
        try { fhrS.update({ time: t, value: fhrVals[i] }) } catch { /* ignore out-of-order */ }
      }
      for (let i = 0; i < ucVals.length; i++) {
        const t = (tStart + i * step) as Time
        try { ucS.update({ time: t, value: ucVals[i] }) } catch { /* ignore out-of-order */ }
      }

      if (fhrVals.length > 0) nextTimeFHR.current = tStart + fhrVals.length * step
      if (ucVals.length > 0)  nextTimeUC.current  = tStart + ucVals.length  * step
    })

    return unsubscribe
  }, [bedId, compact])

  // ── Baseline price line (skipped in compact mode) ───────────────
  // Draws a dashed horizontal line at the computed baseline BPM.
  // Gives the clinician visual reference of what the algorithm sees as baseline.
  useEffect(() => {
    if (compact) return
    const fhr = fhrSeries.current
    if (!fhr) return

    // Remove previous line before drawing new one
    if (baselineLine.current) {
      try { fhr.removePriceLine(baselineLine.current) } catch { /* ignore */ }
      baselineLine.current = null
    }

    if (baselineBpm && baselineBpm > 50) {
      try {
        baselineLine.current = fhr.createPriceLine({
          price: baselineBpm,
          color: COLOR_UC,
          lineWidth: 1,
          lineStyle: LineStyle.Dashed,
          axisLabelVisible: true,
          title: 'Baseline',
        })
      } catch { /* ignore if series not ready */ }
    }
  }, [baselineBpm, compact])

  // ── God Mode: event markers on FHR series (skipped in compact mode) ──
  useEffect(() => {
    if (compact) return
    const fhr = fhrSeries.current
    if (!fhr) return

    if (!activeEvents?.length) {
      try { fhr.setMarkers([]) } catch { /* ignore if chart removed */ }
      return
    }

    const markers = activeEvents.flatMap(e => {
      const label = e.event_type.split('_')[0].toUpperCase().slice(0, 4)
      const result: Parameters<typeof fhr.setMarkers>[0] = [{
        time: (e.start_sample / 4.0) as Time,
        position: 'belowBar',
        color: COLOR_FHR,
        shape: 'arrowDown',
        text: label,
      }]
      if (!e.still_ongoing && e.end_sample !== null) {
        result.push({
          time: (e.end_sample / 4.0) as Time,
          position: 'aboveBar',
          color: COLOR_UC,
          shape: 'arrowUp',
          text: '',
        })
      }
      return result
    }).sort((a, b) => (a.time as number) - (b.time as number))

    try { fhr.setMarkers(markers) } catch { /* ignore if chart removed */ }
  }, [activeEvents, compact])
}

// src/hooks/useCTGChart.ts
// Creates a lightweight-charts instance in the provided container ref.
// Two panes: FHR (top, right axis) and UC (bottom, left axis).
// Subscribes to chartUpdateBus and calls series.update() — NEVER setData().
// BUG-10: chart updates come from the bus, completely decoupled from React render.

import { useEffect, useRef } from 'react'
import { createChart, ColorType, LineStyle } from 'lightweight-charts'
import type { IChartApi, ISeriesApi, Time } from 'lightweight-charts'
import { chartUpdateBus } from '../utils/chartUpdateBus'

// B&W palette (PLAN.md §8)
const COLOR_FHR = '#111827'
const COLOR_UC  = '#6b7280'
const COLOR_BG  = '#ffffff'
const COLOR_GRID = '#e5e7eb'

export function useCTGChart(
  containerRef: React.RefObject<HTMLElement | null>,
  bedId: string,
) {
  const chartRef  = useRef<IChartApi | null>(null)
  const fhrSeries = useRef<ISeriesApi<'Line'> | null>(null)
  const ucSeries  = useRef<ISeriesApi<'Line'> | null>(null)

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
      grid: {
        vertLines: { color: COLOR_GRID, style: LineStyle.Dotted },
        horzLines: { color: COLOR_GRID, style: LineStyle.Dotted },
      },
      rightPriceScale: { visible: true, borderColor: COLOR_GRID },
      leftPriceScale: { visible: true, borderColor: COLOR_GRID },
      timeScale: {
        borderColor: COLOR_GRID,
        timeVisible: true,
        secondsVisible: false,
      },
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
      chartRef.current = null
      fhrSeries.current = null
      ucSeries.current = null
    }
  }, [containerRef])   // re-create only if container changes

  // ── Subscribe to chartUpdateBus (BUG-10) ──────────────────────
  useEffect(() => {
    if (!bedId) return

    const unsubscribe = chartUpdateBus.subscribe(bedId, (fhrVals, ucVals, tStart) => {
      const fhr = fhrSeries.current
      const uc  = ucSeries.current
      if (!fhr || !uc) return

      const step = 0.25   // 4 Hz → 0.25 s per sample

      // Advance per-series time counters from tStart (server epoch) on first
      // call; subsequently just sequence them at 4 Hz.

      // FHR samples
      for (let i = 0; i < fhrVals.length; i++) {
        const t = (tStart + i * step) as Time
        try { fhr.update({ time: t, value: fhrVals[i] }) } catch { /* ignore out-of-order */ }
      }
      if (fhrVals.length > 0) {
        nextTimeFHR.current = tStart + fhrVals.length * step
      }

      // UC samples
      for (let i = 0; i < ucVals.length; i++) {
        const t = (tStart + i * step) as Time
        try { uc.update({ time: t, value: ucVals[i] }) } catch { /* ignore out-of-order */ }
      }
      if (ucVals.length > 0) {
        nextTimeUC.current = tStart + ucVals.length * step
      }
    })

    return unsubscribe
  }, [bedId])
}

// src/hooks/useCTGChart.ts
// Creates a lightweight-charts instance in the provided container ref.
// Two panes: FHR (top, right axis) and UC (bottom, left axis).
// Used exclusively for the full-size detail chart in DetailView.
// Mini-strip in BedCard uses Sparkline instead.
//
// Live-tick batching (Ruba 4):
//   Incoming ticks are buffered; a single requestAnimationFrame drains the buffer.
//   This means at most one chart repaint per display frame regardless of tick rate.
//
// History loading (Ruba 4):
//   setData() is deferred to the next frame so DetailView's shell (header, risk gauge,
//   buttons) paints first. The chart subscribes AFTER setData so live ticks always
//   have t > history end, preventing out-of-order errors.

import { useEffect, useRef } from 'react'
import { createChart, ColorType, LineStyle } from 'lightweight-charts'
import type { IChartApi, ISeriesApi, IPriceLine, Time } from 'lightweight-charts'
import { chartUpdateBus } from '../utils/chartUpdateBus'
import { formatIsraelTime } from '../utils/israelTime'
import type { DetectionEvent, EventAnnotation } from '../types'

const COLOR_FHR   = '#111827'
const COLOR_UC    = '#6b7280'
const COLOR_BG    = '#ffffff'
const COLOR_GRID  = '#e5e7eb'
const COLOR_ALERT = '#dc2626'

function getPointColor(
  timeSec: number,
  events: DetectionEvent[],
): string | undefined {
  for (const e of events) {
    const startT = e.start_sample / 4.0
    const endT = e.end_sample !== null ? e.end_sample / 4.0 : Infinity
    if (timeSec >= startT && timeSec < endT) return COLOR_ALERT
  }
  return undefined
}

export function useCTGChart(
  containerRef: React.RefObject<HTMLElement | null>,
  bedId: string,
  activeEvents?: EventAnnotation[],
  baselineBpm?: number,
  detectionHistory: DetectionEvent[] = [],
  recordingStartWallTs = 0,
) {
  const chartRef     = useRef<IChartApi | null>(null)
  const fhrSeries    = useRef<ISeriesApi<'Line'> | null>(null)
  const ucSeries     = useRef<ISeriesApi<'Line'> | null>(null)
  const baselineLine = useRef<IPriceLine | null>(null)
  const detectionRef = useRef(detectionHistory)
  detectionRef.current = detectionHistory

  // ── Create chart once (no compact variant — Sparkline handles ward tiles) ──
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
      leftPriceScale:  { visible: true, borderColor: COLOR_GRID },
      localization: {
        timeFormatter: (time: Time) => formatIsraelTime(recordingStartWallTs + Number(time), true),
      },
      timeScale: {
        borderColor: COLOR_GRID,
        timeVisible: true,
        secondsVisible: false,
        tickMarkFormatter: (time: Time) => formatIsraelTime(recordingStartWallTs + Number(time), false),
      },
      crosshair: { mode: 0 },
    })
    chartRef.current = chart

    const fhr = chart.addLineSeries({
      color: COLOR_FHR,
      lineWidth: 1,
      priceScaleId: 'right',
      priceFormat: { type: 'price', precision: 0, minMove: 1 },
      title: 'FHR',
    })
    chart.priceScale('right').applyOptions({ scaleMargins: { top: 0.05, bottom: 0.55 } })
    fhrSeries.current = fhr

    const uc = chart.addLineSeries({
      color: COLOR_UC,
      lineWidth: 1,
      priceScaleId: 'left',
      priceFormat: { type: 'price', precision: 0, minMove: 1 },
      title: 'UC',
    })
    chart.priceScale('left').applyOptions({ scaleMargins: { top: 0.55, bottom: 0.05 } })
    ucSeries.current = uc

    const ro = new ResizeObserver(() => {
      chart.resize(container.clientWidth, container.clientHeight)
    })
    ro.observe(container)

    return () => {
      ro.disconnect()
      chart.remove()
      chartRef.current     = null
      fhrSeries.current    = null
      ucSeries.current     = null
      baselineLine.current = null
    }
  }, [containerRef, recordingStartWallTs])

  // ── History + live subscription with RAF batching ──────────────────────
  useEffect(() => {
    if (!bedId) return

    let live = true
    let rafHandle: number | null = null
    let unsubLive: (() => void) | null = null

    // Pending point buffers — drained by the RAF callback
    const pendingFhr: { time: Time; value: number; color?: string }[] = []
    const pendingUc:  { time: Time; value: number }[] = []

    const flush = () => {
      rafHandle = null
      const fhrS = fhrSeries.current
      const ucS  = ucSeries.current
      if (!fhrS || !ucS) {
        pendingFhr.length = 0
        pendingUc.length  = 0
        return
      }
      // Drain accumulated ticks in one pass — one chart repaint per frame
      const fb = pendingFhr.splice(0)
      const ub = pendingUc.splice(0)
      for (const pt of fb) try { fhrS.update(pt) } catch { /* ignore out-of-order */ }
      for (const pt of ub) try { ucS.update(pt)  } catch { /* ignore out-of-order */ }
    }

    // Defer history + subscription to the next frame so DetailView shell renders first.
    // Subscribe AFTER setData so all live ticks have t > history end — no out-of-order errors.
    requestAnimationFrame(() => {
      if (!live) return

      const fhrS = fhrSeries.current
      const ucS  = ucSeries.current

      if (fhrS && ucS) {
        const hist = chartUpdateBus.getHistory(bedId)
        if (hist) {
          const step = 0.25
          try {
            fhrS.setData(hist.fhrVals.map((v, i) => {
              const t = hist.tStart + i * step
              const c = getPointColor(t, detectionRef.current)
              return c ? { time: t as Time, value: v, color: c } : { time: t as Time, value: v }
            }))
            ucS.setData(hist.ucVals.map((v,  i) => ({ time: (hist.tStart + i * step) as Time, value: v })))
          } catch { /* chart removed between frame scheduling and execution */ }
        }
      }

      if (!live) return  // component unmounted before frame fired

      // Subscribe for live ticks AFTER history is loaded
      unsubLive = chartUpdateBus.subscribe(bedId, (fhrVals, ucVals, tStart) => {
        if (!live) return
        const step = 0.25
        for (let i = 0; i < fhrVals.length; i++) {
          const t = tStart + i * step
          const c = getPointColor(t, detectionRef.current)
          pendingFhr.push(c
            ? { time: t as Time, value: fhrVals[i], color: c }
            : { time: t as Time, value: fhrVals[i] }
          )
        }
        for (let i = 0; i < ucVals.length; i++) {
          pendingUc.push({ time: (tStart + i * step) as Time, value: ucVals[i] })
        }
        // Schedule a single flush for this frame — idempotent if already scheduled
        if (rafHandle === null) rafHandle = requestAnimationFrame(flush)
      })
    })

    return () => {
      live = false
      if (rafHandle !== null) { cancelAnimationFrame(rafHandle); rafHandle = null }
      unsubLive?.()
      pendingFhr.length = 0
      pendingUc.length  = 0
    }
  }, [bedId])

  // ── Retroactive red coloring when detection events change ──────────────
  // When a new event opens (with start_sample in the past), we need to
  // re-color already-rendered points. Rebuilds FHR data from chartUpdateBus.
  useEffect(() => {
    if (!bedId || detectionHistory.length === 0) return
    const fhrS = fhrSeries.current
    if (!fhrS) return

    const hist = chartUpdateBus.getHistory(bedId)
    if (!hist) return

    requestAnimationFrame(() => {
      if (!fhrSeries.current) return
      const step = 0.25
      try {
        fhrSeries.current.setData(hist.fhrVals.map((v, i) => {
          const t = hist.tStart + i * step
          const c = getPointColor(t, detectionHistory)
          return c ? { time: t as Time, value: v, color: c } : { time: t as Time, value: v }
        }))
      } catch { /* chart may have been removed */ }
    })
  }, [detectionHistory, bedId])

  // ── Baseline price line ────────────────────────────────────────────────
  useEffect(() => {
    const fhr = fhrSeries.current
    if (!fhr) return

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
      } catch { /* series not ready */ }
    }
  }, [baselineBpm])

  // ── God Mode + Explainability markers on FHR series ───────────────────
  useEffect(() => {
    const fhr = fhrSeries.current
    if (!fhr) return

    if (!activeEvents?.length && detectionHistory.length === 0) {
      try { fhr.setMarkers([]) } catch { /* ignore */ }
      return
    }

    const godMarkers = (activeEvents ?? []).flatMap(e => {
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
    })

    const detectionLabels: Record<string, string> = {
      lr_high_risk: 'RISK',
      late_deceleration: 'LATE',
      variable_deceleration: 'VAR',
      prolonged_deceleration: 'PROL',
      bradycardia: 'BRAD',
      tachycardia: 'TACH',
      low_variability: 'LOWV',
      sinusoidal: 'SIN',
      tachysystole: 'TS',
    }

    const detectionMarkers = detectionHistory.flatMap(e => {
      const label = detectionLabels[e.event_type] ?? e.event_type.slice(0, 4).toUpperCase()
      const result: Parameters<typeof fhr.setMarkers>[0] = [{
        time: (e.start_sample / 4.0) as Time,
        position: 'belowBar',
        color: COLOR_ALERT,
        shape: 'arrowDown',
        text: label,
      }]
      if (!e.still_ongoing && e.end_sample !== null) {
        result.push({
          time: (e.end_sample / 4.0) as Time,
          position: 'aboveBar',
          color: COLOR_ALERT,
          shape: 'arrowUp',
          text: '',
        })
      }
      if (e.event_type === 'lr_high_risk' && e.peak_sample !== e.start_sample) {
        result.push({
          time: (e.peak_sample / 4.0) as Time,
          position: 'inBar',
          color: COLOR_ALERT,
          shape: 'circle',
          text: '',
        })
      }
      return result
    })

    const markers = [...godMarkers, ...detectionMarkers]
      .sort((a, b) => (a.time as number) - (b.time as number))

    try { fhr.setMarkers(markers) } catch { /* ignore */ }
  }, [activeEvents, detectionHistory])

  return { chartApi: chartRef.current }
}

// src/utils/chartUpdateBus.ts
// Singleton pub/sub bus that decouples CTG chart updates from React render.
//
// WebSocket frame arrives → chartUpdateBus.publish() → chart series.update()
// This bypasses the React render cycle entirely (BUG-10):
//   - Store update triggers re-render of WardView/BedCard cards
//   - Chart update is delivered directly via this bus to useCTGChart
//   - series.update() is called EXACTLY ONCE per WebSocket frame per bed
//   - No zigzag artifacts from double-invoke (React Strict Mode or unrelated re-renders)

type ChartCallback = (fhrVals: number[], ucVals: number[], tStart: number) => void

class ChartUpdateBus {
  private subs = new Map<string, ChartCallback>()

  /** Subscribe a chart handler for a specific bed. Returns an unsubscribe fn. */
  subscribe(bedId: string, cb: ChartCallback): () => void {
    this.subs.set(bedId, cb)
    return () => this.subs.delete(bedId)
  }

  /** Publish chart data directly to the subscribed handler (bypass React). */
  publish(bedId: string, fhrVals: number[], ucVals: number[], tStart: number): void {
    this.subs.get(bedId)?.(fhrVals, ucVals, tStart)
  }
}

// Module-level singleton — one bus for the entire app lifetime
export const chartUpdateBus = new ChartUpdateBus()

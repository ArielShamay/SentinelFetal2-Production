// src/utils/alertSound.ts
// Web Audio API — two-tone alert (§11.10).
// No external dependencies. Called only on alert state transitions (false → true).

let audioCtx: AudioContext | null = null
let muted = false

function getAudioCtx(): AudioContext {
  if (!audioCtx) audioCtx = new AudioContext()
  return audioCtx
}

/** Play a two-tone clinical alert: 880 Hz → 1100 Hz, 500ms */
export function playAlertTone(): void {
  if (muted) return
  try {
    const ctx = getAudioCtx()
    const osc = ctx.createOscillator()
    const gain = ctx.createGain()

    osc.connect(gain)
    gain.connect(ctx.destination)

    osc.frequency.setValueAtTime(880, ctx.currentTime)
    osc.frequency.setValueAtTime(1100, ctx.currentTime + 0.15)

    gain.gain.setValueAtTime(0.3, ctx.currentTime)
    gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.5)

    osc.start(ctx.currentTime)
    osc.stop(ctx.currentTime + 0.5)
  } catch {
    // AudioContext may be suspended until user interaction — fail silently
  }
}

export function setMuted(value: boolean): void {
  muted = value
}

export function isMuted(): boolean {
  return muted
}

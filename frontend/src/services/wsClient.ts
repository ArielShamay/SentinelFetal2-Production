// src/services/wsClient.ts
// WebSocket singleton: manages connection lifecycle with exponential-backoff reconnect.
// Consumers subscribe to raw messages and connection-status changes.
// useBedStream.ts uses this as its transport layer.

const MIN_BACKOFF_MS = 500
const MAX_BACKOFF_MS = 10_000

type MessageHandler = (raw: string) => void
type StatusHandler  = (connected: boolean) => void

class WSClient {
  private ws: WebSocket | null = null
  private attempt = 0
  private timer: ReturnType<typeof setTimeout> | null = null
  private msgHandlers    = new Set<MessageHandler>()
  private statusHandlers = new Set<StatusHandler>()
  private _url = ''
  private _active = false

  /** Open the connection. Idempotent if already connected to the same URL. */
  connect(url: string): void {
    if (this._active && this._url === url) return
    this._url = url
    this._active = true
    this._connect()
  }

  /** Tear down the connection and cancel any pending reconnect timer. */
  disconnect(): void {
    this._active = false
    if (this.timer) { clearTimeout(this.timer); this.timer = null }
    if (this.ws)    { this.ws.close(); this.ws = null }
  }

  /** Subscribe to raw string messages. Returns an unsubscribe function. */
  onMessage(handler: MessageHandler): () => void {
    this.msgHandlers.add(handler)
    return () => this.msgHandlers.delete(handler)
  }

  /** Subscribe to connected/disconnected status changes. Returns an unsubscribe fn. */
  onStatus(handler: StatusHandler): () => void {
    this.statusHandlers.add(handler)
    return () => this.statusHandlers.delete(handler)
  }

  private _connect(): void {
    if (!this._active) return

    const ws = new WebSocket(this._url)
    this.ws = ws

    ws.onopen = () => {
      this.attempt = 0
      this.statusHandlers.forEach(h => h(true))
    }

    ws.onmessage = (ev: MessageEvent<string>) => {
      this.msgHandlers.forEach(h => h(ev.data))
    }

    ws.onclose = () => {
      this.ws = null
      this.statusHandlers.forEach(h => h(false))
      if (this._active) this._schedule()
    }

    ws.onerror = () => ws.close()
  }

  private _schedule(): void {
    this.attempt += 1
    const delay = Math.min(MIN_BACKOFF_MS * 2 ** (this.attempt - 1), MAX_BACKOFF_MS)
    this.timer = setTimeout(() => this._connect(), delay)
  }
}

/** Module-level singleton — one WS connection for the entire app. */
export const wsClient = new WSClient()

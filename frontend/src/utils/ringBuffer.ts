// src/utils/ringBuffer.ts
// Typed circular ring buffer. Push is O(1); toArray is O(n), called rarely.

export class RingBuffer<T> {
  private buf: T[]
  private head = 0
  readonly size: number

  constructor(size: number) {
    this.size = size
    this.buf = new Array<T>(size)
  }

  push(val: T): void {
    this.buf[this.head % this.size] = val
    this.head++
  }

  /** Returns items in insertion order (oldest first). */
  toArray(): T[] {
    if (this.head <= this.size) return this.buf.slice(0, this.head)
    const idx = this.head % this.size
    return [...this.buf.slice(idx), ...this.buf.slice(0, idx)]
  }

  last(): T | undefined {
    return this.head > 0 ? this.buf[(this.head - 1) % this.size] : undefined
  }

  get length(): number {
    return Math.min(this.head, this.size)
  }
}

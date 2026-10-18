export type CacheLookup<T> = { hit: false } | { hit: true; value: T }

interface Entry<T> {
  value: T
  expiresAt: number
}

// Small in-memory cache with a lifetime per entry and a size cap (oldest entries go first).
export class TtlCache<T> {
  private entries = new Map<string, Entry<T>>()
  private defaultTtlMs: number
  private maxEntries: number
  private now: () => number

  constructor(defaultTtlMs: number, maxEntries: number, now: () => number = Date.now) {
    this.defaultTtlMs = defaultTtlMs
    this.maxEntries = maxEntries
    this.now = now
  }

  get size(): number {
    return this.entries.size
  }

  get(key: string): CacheLookup<T> {
    const entry = this.entries.get(key)
    if (!entry) return { hit: false }
    if (this.now() >= entry.expiresAt) {
      this.entries.delete(key)
      return { hit: false }
    }
    return { hit: true, value: entry.value }
  }

  set(key: string, value: T, ttlMs: number = this.defaultTtlMs): void {
    this.entries.delete(key)
    this.entries.set(key, { value, expiresAt: this.now() + ttlMs })
    while (this.entries.size > this.maxEntries) {
      this.entries.delete(this.entries.keys().next().value as string)
    }
  }
}

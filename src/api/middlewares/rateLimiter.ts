export interface RateDecision {
  allowed: boolean
  retryAfterSeconds: number
}

interface Bucket {
  tokens: number
  updatedAt: number
}

// Token bucket per key. In memory, so each server instance counts for itself; Cloud Run's
// --max-instances bounds the total. maxKeys keeps a flood of distinct addresses from growing memory.
export class RateLimiter {
  private buckets = new Map<string, Bucket>()
  private capacity: number
  private refillPerSecond: number
  private now: () => number
  private maxKeys: number

  // (Node's type stripping has no constructor parameter properties, hence the explicit fields.)
  constructor(capacity: number, refillPerSecond: number, now: () => number = Date.now, maxKeys = 10_000) {
    this.capacity = capacity
    this.refillPerSecond = refillPerSecond
    this.now = now
    this.maxKeys = maxKeys
  }

  get size(): number {
    return this.buckets.size
  }

  take(key: string): RateDecision {
    const now = this.now()
    const known = this.buckets.get(key)
    const refilled = known
      ? Math.min(this.capacity, known.tokens + ((now - known.updatedAt) / 1000) * this.refillPerSecond)
      : this.capacity

    const allowed = refilled >= 1
    const bucket = { tokens: allowed ? refilled - 1 : refilled, updatedAt: now }

    // Re-inserting moves the key to the end, so the Map's first key is always the least recently seen.
    this.buckets.delete(key)
    this.buckets.set(key, bucket)
    while (this.buckets.size > this.maxKeys) {
      this.buckets.delete(this.buckets.keys().next().value as string)
    }

    return { allowed, retryAfterSeconds: allowed ? 0 : Math.ceil((1 - bucket.tokens) / this.refillPerSecond) }
  }
}

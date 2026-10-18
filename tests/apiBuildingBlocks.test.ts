import { test } from 'node:test'
import assert from 'node:assert/strict'
import { RateLimiter } from '../src/api/middlewares/rateLimiter.ts'
import { TtlCache } from '../src/api/middlewares/ttlCache.ts'
import { clientIp } from '../src/api/middlewares/clientIp.ts'
import { assertPublicKey } from '../src/api/middlewares/keySafety.ts'

function clock(start = 0) {
  let t = start
  return { now: () => t, advance: (ms: number) => { t += ms } }
}

test('rate limiter allows a burst up to its capacity and then refuses', () => {
  const c = clock()
  const limiter = new RateLimiter(3, 1, c.now)
  assert.equal(limiter.take('a').allowed, true)
  assert.equal(limiter.take('a').allowed, true)
  assert.equal(limiter.take('a').allowed, true)
  assert.equal(limiter.take('a').allowed, false)
})

test('rate limiter refills over time and reports when to retry', () => {
  const c = clock()
  const limiter = new RateLimiter(2, 0.5, c.now) // one token every 2 seconds
  limiter.take('a'); limiter.take('a')
  const refused = limiter.take('a')
  assert.deepEqual(refused, { allowed: false, retryAfterSeconds: 2 })
  c.advance(1000)
  assert.equal(limiter.take('a').retryAfterSeconds, 1)
  c.advance(1000)
  assert.equal(limiter.take('a').allowed, true)
})

test('rate limiter never holds more than its capacity however long it idles', () => {
  const c = clock()
  const limiter = new RateLimiter(2, 10, c.now)
  limiter.take('a')
  c.advance(60 * 60 * 1000)
  assert.equal(limiter.take('a').allowed, true)
  assert.equal(limiter.take('a').allowed, true)
  assert.equal(limiter.take('a').allowed, false)
})

test('rate limiter keeps keys apart and bounds its memory', () => {
  const c = clock()
  const limiter = new RateLimiter(1, 1, c.now, 3)
  assert.equal(limiter.take('a').allowed, true)
  assert.equal(limiter.take('b').allowed, true)
  assert.equal(limiter.take('a').allowed, false)
  for (const key of ['c', 'd', 'e', 'f']) limiter.take(key)
  assert.ok(limiter.size <= 3, `size was ${limiter.size}`)
})

test('cache returns what was stored until it expires', () => {
  const c = clock()
  const cache = new TtlCache<string | null>(1000, 10, c.now)
  assert.deepEqual(cache.get('k'), { hit: false })
  cache.set('k', 'v')
  assert.deepEqual(cache.get('k'), { hit: true, value: 'v' })
  c.advance(999)
  assert.equal(cache.get('k').hit, true)
  c.advance(2)
  assert.equal(cache.get('k').hit, false)
})

test('cache can hold null and a per-entry lifetime', () => {
  const c = clock()
  const cache = new TtlCache<string | null>(10_000, 10, c.now)
  cache.set('none', null, 100)
  assert.deepEqual(cache.get('none'), { hit: true, value: null })
  c.advance(101)
  assert.equal(cache.get('none').hit, false)
})

test('cache drops its oldest entries when full', () => {
  const c = clock()
  const cache = new TtlCache<number>(1000, 2, c.now)
  cache.set('a', 1); cache.set('b', 2); cache.set('c', 3)
  assert.equal(cache.size, 2)
  assert.equal(cache.get('a').hit, false)
  assert.equal(cache.get('c').hit, true)
})

test('client ip is the right-most forwarded address, which the platform appended', () => {
  assert.equal(clientIp('6.6.6.6, 1.2.3.4', '10.0.0.1'), '1.2.3.4')
  assert.equal(clientIp(' 1.2.3.4 ', '10.0.0.1'), '1.2.3.4')
  assert.equal(clientIp(undefined, '10.0.0.1'), '10.0.0.1')
  assert.equal(clientIp('', undefined), 'unknown')
})

function jwt(payload: object) {
  const part = (value: object) => Buffer.from(JSON.stringify(value)).toString('base64url')
  return `${part({ alg: 'HS256' })}.${part(payload)}.signature`
}

test('the public api refuses privileged keys', () => {
  assert.throws(() => assertPublicKey('sb_secret_abc123'), /secret/i)
  assert.throws(() => assertPublicKey(jwt({ role: 'service_role' })), /service_role/)
})

test('the public api accepts publishable and anon keys', () => {
  assert.doesNotThrow(() => assertPublicKey('sb_publishable_abc123'))
  assert.doesNotThrow(() => assertPublicKey(jwt({ role: 'anon' })))
})

test('the public api needs a key at all', () => {
  assert.throws(() => assertPublicKey(''), /SUPABASE_PUBLISHABLE_KEY/)
  assert.throws(() => assertPublicKey(undefined), /SUPABASE_PUBLISHABLE_KEY/)
})

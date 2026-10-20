import { test } from 'node:test'
import assert from 'node:assert/strict'
import { createRouter } from '../src/api/routes/router.ts'
import { RateLimiter } from '../src/api/middlewares/rateLimiter.ts'
import { TtlCache } from '../src/api/middlewares/ttlCache.ts'
import type { HintRow, HintsRepository } from '../src/api/types.ts'
import type { HintsPayload } from '../src/api/controllers/hintsController.ts'

function row(level: number, overrides: Partial<HintRow> = {}): HintRow {
  return {
    problem_id: '1944_C',
    contest_id: 1944,
    index: 'C',
    name: 'MEX Game 1',
    rating: 1500,
    tags: ['games'],
    hints_problem_id: '1944_C',
    hint_level: level,
    content: `Hint ${level}`,
    grounded_in_tutorial: true,
    generated_at: '2024-01-02T00:00:00+00:00',
    ...overrides,
  }
}

const fiveRows = () => [1, 2, 3, 4, 5].map((level) => row(level))

function setup(options: { rows?: HintRow[]; error?: Error; capacity?: number } = {}) {
  let time = 1_000_000
  const calls: Array<[number, string]> = []
  const logs: Array<Record<string, unknown>> = []
  const repository: HintsRepository = {
    async findHints(contestId, index) {
      calls.push([contestId, index])
      if (options.error) throw options.error
      return options.rows ?? fiveRows()
    },
  }
  const now = () => time
  const router = createRouter({
    repository,
    limiter: new RateLimiter(options.capacity ?? 100, 1, now),
    cache: new TtlCache<HintsPayload | null>(600_000, 100, now),
    now,
    log: (entry) => logs.push(entry),
  })
  return { router, calls, logs, advance: (ms: number) => { time += ms } }
}

const get = (path: string, ip = '1.1.1.1', method = 'GET') => ({ method, path, ip })

test('returns all hint levels for a finished problem', async () => {
  const { router } = setup()
  const response = await router(get('/v1/problems/1944/C/hints'))

  assert.equal(response.status, 200)
  assert.deepEqual(JSON.parse(response.body), {
    problem: { id: '1944_C', contestId: 1944, index: 'C', name: 'MEX Game 1', rating: 1500, tags: ['games'] },
    duplicateOf: null,
    hints: [1, 2, 3, 4, 5].map((level) => ({ level, content: `Hint ${level}` })),
    groundedInTutorial: true,
    generatedAt: '2024-01-02T00:00:00+00:00',
  })
})

test('the success response is cacheable and open to browser extensions', async () => {
  const { router } = setup()
  const { headers } = await router(get('/v1/problems/1944/C/hints'))
  assert.equal(headers['Content-Type'], 'application/json; charset=utf-8')
  assert.match(headers['Cache-Control'], /public/)
  assert.match(headers['Cache-Control'], /s-maxage=3600/)
  assert.equal(headers['Access-Control-Allow-Origin'], '*')
  assert.equal(headers['X-Content-Type-Options'], 'nosniff')
})

test('hints are sorted by level and a duplicate says which problem it shares hints with', async () => {
  const rows = [3, 1, 2, 5, 4].map((level) => row(level, { hints_problem_id: '1943_A' }))
  const { router } = setup({ rows })
  const body = JSON.parse((await router(get('/v1/problems/1944/C/hints'))).body)
  assert.deepEqual(body.hints.map((hint: { level: number }) => hint.level), [1, 2, 3, 4, 5])
  assert.equal(body.duplicateOf, '1943_A')
})

test('hints not grounded in a tutorial are flagged, null tags become an empty list', async () => {
  const rows = fiveRows().map((r, i) => ({ ...r, tags: null, grounded_in_tutorial: i !== 2, generated_at: `2024-01-0${i + 1}T00:00:00+00:00` }))
  const body = JSON.parse((await setup({ rows }).router(get('/v1/problems/1944/C/hints'))).body)
  assert.equal(body.groundedInTutorial, false)
  assert.deepEqual(body.problem.tags, [])
  assert.equal(body.generatedAt, '2024-01-05T00:00:00+00:00')
})

test('the index is case-insensitive and reaches the database upper-cased', async () => {
  const { router, calls } = setup()
  await router(get('/v1/problems/1944/c/hints'))
  await router(get('/v1/problems/1943/d1/hints/'))
  assert.deepEqual(calls, [[1944, 'C'], [1943, 'D1']])
})

test('anything that is not a plausible problem id is a 400 and never reaches the database', async () => {
  const { router, calls } = setup()
  for (const path of ['/v1/problems/abc/A/hints', '/v1/problems/1944/AAA/hints', '/v1/problems/1944/1/hints',
                      '/v1/problems/99999999/A/hints', '/v1/problems/1944/A%27%20OR%201=1/hints', '/v1/problems/-1/A/hints']) {
    const response = await router(get(path))
    assert.equal(response.status, 400, path)
    assert.equal(JSON.parse(response.body).error.code, 'invalid_problem')
  }
  assert.deepEqual(calls, [])
})

test('a problem without public hints is a plain 404 that does not say why', async () => {
  const { router } = setup({ rows: [] })
  const response = await router(get('/v1/problems/1944/C/hints'))
  assert.equal(response.status, 404)
  assert.equal(JSON.parse(response.body).error.code, 'not_found')
  assert.match(response.headers['Cache-Control'], /max-age=60/)
  assert.doesNotMatch(response.body, /contest|phase|finished|live/i)
})

test('unknown paths are 404s', async () => {
  const { router, calls } = setup()
  for (const path of ['/v1', '/v1/problems', '/v1/problems/1944/C', '/v2/problems/1944/C/hints', '/admin']) {
    assert.equal((await router(get(path))).status, 404, path)
  }
  assert.deepEqual(calls, [])
})

test('only reading is allowed', async () => {
  const { router } = setup()
  for (const method of ['POST', 'PUT', 'DELETE', 'PATCH']) {
    const response = await router(get('/v1/problems/1944/C/hints', '1.1.1.1', method))
    assert.equal(response.status, 405, method)
    assert.equal(response.headers['Allow'], 'GET, HEAD, OPTIONS')
  }
})

test('health is read-only too', async () => {
  const response = await setup().router(get('/v1/health', '1.1.1.1', 'POST'))
  assert.equal(response.status, 405)
  assert.equal(response.headers['Allow'], 'GET, HEAD, OPTIONS')
})

test('HEAD answers like GET without a body', async () => {
  const { router } = setup()
  const head = await router(get('/v1/problems/1944/C/hints', '1.1.1.1', 'HEAD'))
  assert.equal(head.status, 200)
  assert.equal(head.body, '')
  assert.match(head.headers['Cache-Control'], /public/)
})

test('preflight requests are answered with the cors headers', async () => {
  const { router, calls } = setup()
  const response = await router(get('/v1/problems/1944/C/hints', '1.1.1.1', 'OPTIONS'))
  assert.equal(response.status, 204)
  assert.equal(response.body, '')
  assert.equal(response.headers['Access-Control-Allow-Origin'], '*')
  assert.equal(response.headers['Access-Control-Allow-Methods'], 'GET, HEAD, OPTIONS')
  assert.deepEqual(calls, [])
})

test('a browser may send X-Client, and may read Retry-After on a rate-limit answer', async () => {
  const { router } = setup({ capacity: 1 })
  const preflight = await router(get('/v1/problems/1944/C/hints', '1.1.1.1', 'OPTIONS'))
  assert.match(preflight.headers['Access-Control-Allow-Headers'], /X-Client/i)
  await router(get('/v1/problems/1944/A/hints', '5.5.5.5'))
  const refused = await router(get('/v1/problems/1944/B/hints', '5.5.5.5'))
  assert.equal(refused.status, 429)
  assert.match(refused.headers['Access-Control-Expose-Headers'], /Retry-After/i)
})

test('health needs no database', async () => {
  const { router, calls } = setup({ error: new Error('db down') })
  const response = await router(get('/v1/health'))
  assert.equal(response.status, 200)
  assert.deepEqual(JSON.parse(response.body), { status: 'ok' })
  assert.deepEqual(calls, [])
})

test('repeat requests are served from memory', async () => {
  const { router, calls, advance } = setup()
  await router(get('/v1/problems/1944/C/hints'))
  await router(get('/v1/problems/1944/c/hints', '2.2.2.2'))
  assert.equal(calls.length, 1)
  advance(9 * 60_000)
  await router(get('/v1/problems/1944/C/hints'))
  assert.equal(calls.length, 1)
  advance(2 * 60_000)
  await router(get('/v1/problems/1944/C/hints'))
  assert.equal(calls.length, 2)
})

test('a missing problem is remembered only briefly, so new hints show up soon', async () => {
  const { router, calls, advance } = setup({ rows: [] })
  await router(get('/v1/problems/1944/C/hints'))
  await router(get('/v1/problems/1944/C/hints'))
  assert.equal(calls.length, 1)
  advance(61_000)
  await router(get('/v1/problems/1944/C/hints'))
  assert.equal(calls.length, 2)
})

test('simultaneous requests for the same cold problem make one database call', async () => {
  const { router, calls } = setup()
  const responses = await Promise.all([1, 2, 3, 4].map((n) => router(get('/v1/problems/1944/C/hints', `9.9.9.${n}`))))
  assert.ok(responses.every((response) => response.status === 200))
  assert.equal(calls.length, 1)
})

test('a client that asks too often gets 429 with Retry-After, and the database is spared', async () => {
  const { router, calls } = setup({ capacity: 2 })
  await router(get('/v1/problems/1944/A/hints', '5.5.5.5'))
  await router(get('/v1/problems/1944/B/hints', '5.5.5.5'))
  const refused = await router(get('/v1/problems/1944/C/hints', '5.5.5.5'))

  assert.equal(refused.status, 429)
  assert.equal(JSON.parse(refused.body).error.code, 'rate_limited')
  assert.ok(Number(refused.headers['Retry-After']) >= 1)
  assert.equal(refused.headers['Cache-Control'], 'no-store')
  assert.equal(calls.length, 2)

  const other = await router(get('/v1/problems/1944/C/hints', '6.6.6.6'))
  assert.equal(other.status, 200)
})

test('health checks and preflights do not use up the rate limit', async () => {
  const { router } = setup({ capacity: 1 })
  for (let i = 0; i < 5; i++) {
    assert.equal((await router(get('/v1/health', '5.5.5.5'))).status, 200)
    assert.equal((await router(get('/v1/problems/1/A/hints', '5.5.5.5', 'OPTIONS'))).status, 204)
  }
  assert.equal((await router(get('/v1/problems/1944/C/hints', '5.5.5.5'))).status, 200)
})

test('a database failure becomes a 503 with no internal details, and is logged', async () => {
  const { router, logs } = setup({ error: new Error('password authentication failed for user postgres') })
  const response = await router(get('/v1/problems/1944/C/hints'))
  assert.equal(response.status, 503)
  assert.equal(JSON.parse(response.body).error.code, 'unavailable')
  assert.doesNotMatch(response.body, /password|postgres/)
  assert.equal(response.headers['Cache-Control'], 'no-store')
  assert.ok(logs.some((entry) => entry.severity === 'ERROR' && String(entry.message).includes('password authentication failed')))
})

test('a failure is not cached', async () => {
  let fail = true
  const repository: HintsRepository = { async findHints() { if (fail) throw new Error('boom'); return fiveRows() } }
  const router = createRouter({ repository, limiter: new RateLimiter(100, 1), cache: new TtlCache<HintsPayload | null>(600_000, 10), log: () => {} })
  assert.equal((await router(get('/v1/problems/1944/C/hints'))).status, 503)
  fail = false
  assert.equal((await router(get('/v1/problems/1944/C/hints'))).status, 200)
})

import { test } from 'node:test'
import assert from 'node:assert/strict'
import http from 'node:http'
import type { AddressInfo } from 'node:net'
import { createApp } from '../src/api/app.ts'
import { createRouter } from '../src/api/routes/router.ts'
import { createSupabaseHintsRepository } from '../src/api/controllers/supabaseHintsRepository.ts'
import { RateLimiter } from '../src/api/middlewares/rateLimiter.ts'
import { TtlCache } from '../src/api/middlewares/ttlCache.ts'
import type { HintRow, HintsRepository } from '../src/api/types.ts'
import type { HintsPayload } from '../src/api/controllers/hintsController.ts'

const sampleRows: HintRow[] = [1, 2].map((level) => ({
  problem_id: '1944_C', contest_id: 1944, index: 'C', name: 'MEX Game 1', rating: 1500, tags: ['games'],
  hints_problem_id: '1944_C', hint_level: level, content: `Hint ${level}`, grounded_in_tutorial: true,
  generated_at: '2024-01-02T00:00:00+00:00',
}))

async function withServer(capacity: number, run: (base: string) => Promise<void>) {
  const repository: HintsRepository = { async findHints() { return sampleRows } }
  const route = createRouter({
    repository,
    limiter: new RateLimiter(capacity, 0.001),
    cache: new TtlCache<HintsPayload | null>(600_000, 100),
    log: () => {},
  })
  const server = http.createServer(createApp(route))
  await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve))
  try {
    await run(`http://127.0.0.1:${(server.address() as AddressInfo).port}`)
  } finally {
    await new Promise((resolve) => server.close(resolve))
  }
}

test('serves hints over real http', async () => {
  await withServer(100, async (base) => {
    const response = await fetch(`${base}/v1/problems/1944/C/hints?utm=ignored`)
    assert.equal(response.status, 200)
    assert.match(response.headers.get('content-type') ?? '', /application\/json/)
    assert.equal(response.headers.get('access-control-allow-origin'), '*')
    const body = await response.json()
    assert.equal(body.problem.id, '1944_C')
    assert.equal(body.hints.length, 2)
  })
})

test('HEAD has no body, OPTIONS is a preflight, POST is refused', async () => {
  await withServer(100, async (base) => {
    const head = await fetch(`${base}/v1/problems/1944/C/hints`, { method: 'HEAD' })
    assert.equal(head.status, 200)
    assert.equal(await head.text(), '')
    assert.equal((await fetch(`${base}/v1/problems/1944/C/hints`, { method: 'OPTIONS' })).status, 204)
    const post = await fetch(`${base}/v1/problems/1944/C/hints`, { method: 'POST', body: '{}' })
    assert.equal(post.status, 405)
    assert.equal(post.headers.get('allow'), 'GET, HEAD, OPTIONS')
  })
})

test('the rate limit counts the right-most forwarded address, so a forged left part does not help', async () => {
  await withServer(1, async (base) => {
    const ask = (forwardedFor: string) => fetch(`${base}/v1/problems/1944/C/hints`, { headers: { 'X-Forwarded-For': forwardedFor } })
    assert.equal((await ask('1.1.1.1, 9.9.9.9')).status, 200)
    assert.equal((await ask('2.2.2.2, 9.9.9.9')).status, 429)
    assert.equal((await ask('2.2.2.2, 8.8.8.8')).status, 200)
  })
})

test('odd request lines do not crash the server', async () => {
  await withServer(100, async (base) => {
    for (const path of ['/%', '/%zz', '//', '/v1/problems/1944/C/hints/%00', '/' + 'a'.repeat(5000)]) {
      const response = await fetch(`${base}${path}`)
      assert.ok([400, 404].includes(response.status), `${path.slice(0, 20)} -> ${response.status}`)
    }
    assert.equal((await fetch(`${base}/v1/health`)).status, 200)
  })
})

test('the supabase repository reads only the public view, filtered and ordered', async () => {
  const seen: Array<{ url: URL; headers: Headers; method: string }> = []
  const stubFetch = (async (input: Request | string | URL, init?: RequestInit) => {
    const request = new Request(input, init)
    seen.push({ url: new URL(request.url), headers: request.headers, method: request.method })
    return Response.json(sampleRows)
  }) as typeof fetch

  const repository = createSupabaseHintsRepository('https://example.supabase.co', 'sb_publishable_test', stubFetch)
  const rows = await repository.findHints(1944, 'C')

  assert.equal(rows.length, 2)
  assert.equal(seen.length, 1)
  assert.equal(seen[0].method, 'GET')
  assert.equal(seen[0].url.pathname, '/rest/v1/public_hints')
  assert.equal(seen[0].url.searchParams.get('contest_id'), 'eq.1944')
  assert.equal(seen[0].url.searchParams.get('index'), 'eq.C')
  assert.equal(seen[0].url.searchParams.get('order'), 'hint_level.asc')
  assert.match(seen[0].url.searchParams.get('select') ?? '', /hint_level/)
  assert.equal(seen[0].headers.get('apikey'), 'sb_publishable_test')
})

test('the supabase repository turns a database error into an exception', async () => {
  const failing = (async () => Response.json({ message: 'boom' }, { status: 500 })) as typeof fetch
  const repository = createSupabaseHintsRepository('https://example.supabase.co', 'sb_publishable_test', failing)
  await assert.rejects(() => repository.findHints(1944, 'C'), /boom/)
})

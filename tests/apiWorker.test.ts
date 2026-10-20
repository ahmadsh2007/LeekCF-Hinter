import { test } from 'node:test'
import assert from 'node:assert/strict'
import { createWorker } from '../src/api/adapters/worker.ts'
import { clientLabel } from '../src/api/middlewares/clientLabel.ts'
import { buildOpenApiDocument } from '../src/api/docs/openapi.ts'
import type { HintRow, HintsRepository } from '../src/api/types.ts'

const rows: HintRow[] = [1, 2].map((level) => ({
  problem_id: '1944_C', contest_id: 1944, index: 'C', name: 'MEX Game 1', rating: 1500, tags: ['games'],
  hints_problem_id: '1944_C', hint_level: level, content: `Hint ${level}`, grounded_in_tutorial: true,
  generated_at: '2024-01-02T00:00:00+00:00',
}))

const env = { SUPABASE_DATABASE_URL: 'https://x.supabase.co', SUPABASE_PUBLISHABLE_KEY: 'sb_publishable_test', PUBLIC_BASE_URL: 'https://hints.example.org' }

function fakeCache() {
  const store = new Map<string, Response>()
  return {
    store,
    async match(request: Request) { return store.get(request.url)?.clone() },
    async put(request: Request, response: Response) { store.set(request.url, response) },
  }
}
const ctx = () => { const pending: Promise<unknown>[] = []; return { waitUntil: (p: Promise<unknown>) => { pending.push(p) }, settle: () => Promise.all(pending) } }

function setup(options: { capacity?: number } = {}) {
  const calls: Array<[number, string]> = []
  const repository: HintsRepository = { async findHints(contestId, index) { calls.push([contestId, index]); return rows } }
  const logs: Array<Record<string, unknown>> = []
  const cache = fakeCache()
  const worker = createWorker({ repository, cache, capacity: options.capacity ?? 100, log: (entry) => logs.push(entry) })
  return { worker, calls, logs, cache }
}

const get = (path: string, headers: Record<string, string> = {}, method = 'GET') =>
  new Request(`https://hints.example.org${path}`, { method, headers })

test('serves hints through the worker interface', async () => {
  const { worker } = setup()
  const response = await worker.fetch(get('/v1/problems/1944/C/hints'), env, ctx())
  assert.equal(response.status, 200)
  assert.match(response.headers.get('content-type') ?? '', /application\/json/)
  assert.equal((await response.json()).hints.length, 2)
})

test('the docs and the openapi document are served too', async () => {
  const { worker } = setup()
  const page = await worker.fetch(get('/'), env, ctx())
  assert.equal(page.status, 200)
  assert.match(page.headers.get('content-type') ?? '', /text\/html/)
  assert.match(await page.text(), /hints\.example\.org/)
  const spec = await (await worker.fetch(get('/v1/openapi.json'), env, ctx())).json()
  assert.equal(spec.servers[0].url, 'https://hints.example.org')
})

test('answers are kept in the edge cache so repeat requests never reach the database', async () => {
  const { worker, calls, cache } = setup()
  const c = ctx()
  await worker.fetch(get('/v1/problems/1944/C/hints'), env, c)
  await c.settle()
  assert.equal(cache.store.size, 1)
  const again = await worker.fetch(get('/v1/problems/1944/C/hints'), env, ctx())
  assert.equal(again.status, 200)
  assert.equal(calls.length, 1)
})

test('a response found in the edge cache is returned as it is and still counted in the usage statistics', async () => {
  const { worker, calls, logs, cache } = setup()
  cache.store.set('https://hints.example.org/v1/problems/1944/C/hints', new Response('FROM THE EDGE CACHE', { status: 200 }))
  const points: any[] = []
  const response = await worker.fetch(get('/v1/problems/1944/C/hints', { 'x-client': 'site-b' }), { ...env, ANALYTICS: { writeDataPoint: (p: any) => points.push(p) } } as any, ctx())
  assert.equal(await response.text(), 'FROM THE EDGE CACHE')
  assert.deepEqual(calls, [])
  const entry = logs.find((e) => e.message === 'request')!
  assert.equal(entry.cache, 'hit')
  assert.equal(entry.client, 'site-b')
  assert.deepEqual(points[0].blobs, ['hints', '200', 'site-b'])
  assert.equal(points[0].doubles[1], 1)
})

test('only public cacheable answers are cached, not errors or rate limits', async () => {
  const { worker, cache } = setup({ capacity: 1 })
  const c = ctx()
  const asClient = { 'cf-connecting-ip': '5.5.5.5' }
  assert.equal((await worker.fetch(get('/v1/problems/abc/A/hints', asClient), env, c)).status, 400)
  assert.equal((await worker.fetch(get('/v1/problems/1944/C/hints', asClient), env, c)).status, 429) // the 400 used the one token
  await c.settle()
  assert.equal(cache.store.size, 0)
})

test('the rate limit counts the client address Cloudflare reports', async () => {
  const { worker } = setup({ capacity: 1 })
  const ask = (ip: string, path: string) => worker.fetch(get(path, { 'cf-connecting-ip': ip }), env, ctx())
  assert.equal((await ask('1.1.1.1', '/v1/problems/1944/A/hints')).status, 200)
  assert.equal((await ask('1.1.1.1', '/v1/problems/1944/B/hints')).status, 429)
  assert.equal((await ask('2.2.2.2', '/v1/problems/1944/B/hints')).status, 200)
})

test('HEAD, preflight and unsupported methods behave like the node server', async () => {
  const { worker } = setup()
  const head = await worker.fetch(get('/v1/problems/1944/C/hints', {}, 'HEAD'), env, ctx())
  assert.equal(head.status, 200)
  assert.equal(await head.text(), '')
  assert.equal((await worker.fetch(get('/v1/problems/1944/C/hints', {}, 'OPTIONS'), env, ctx())).status, 204)
  assert.equal((await worker.fetch(get('/v1/health', {}, 'POST'), env, ctx())).status, 405)
})

test('a missing or privileged key is a clear configuration error that leaks nothing', async () => {
  const logs: Array<Record<string, unknown>> = []
  const worker = createWorker({ cache: fakeCache(), log: (entry) => logs.push(entry) })
  for (const badEnv of [{}, { ...env, SUPABASE_PUBLISHABLE_KEY: 'sb_secret_abc' }, { ...env, SUPABASE_DATABASE_URL: '' }]) {
    const response = await worker.fetch(get('/v1/problems/1944/C/hints'), badEnv as any, ctx())
    assert.equal(response.status, 500)
    assert.doesNotMatch(await response.text(), /sb_secret|supabase|SUPABASE/i)
  }
  assert.ok(logs.some((entry) => entry.severity === 'ERROR' && /SUPABASE|secret/i.test(String(entry.message))))
})

test('every request is logged with its route, status and the app that made it, and no address', async () => {
  const { worker, logs } = setup()
  await worker.fetch(get('/v1/problems/1944/C/hints', { 'x-client': 'my-extension/1.2', 'cf-connecting-ip': '9.9.9.9' }), env, ctx())
  const entry = logs.find((e) => e.message === 'request')!
  assert.equal(entry.route, 'hints')
  assert.equal(entry.status, 200)
  assert.equal(entry.client, 'my-extension/1.2')
  assert.ok(!JSON.stringify(logs).includes('9.9.9.9'))
})

test('an analytics dataset, when bound, receives one data point per request', async () => {
  const points: any[] = []
  const { worker } = setup()
  await worker.fetch(get('/v1/problems/1944/C/hints', { 'x-client': 'site-a' }), { ...env, ANALYTICS: { writeDataPoint: (p: any) => points.push(p) } } as any, ctx())
  assert.equal(points.length, 1)
  assert.deepEqual(points[0].blobs, ['hints', '200', 'site-a'])
  assert.equal(typeof points[0].doubles[0], 'number')
})

test('the client label is the self-declared app name, else the user agent product, else unknown', () => {
  const headers = (h: Record<string, string>) => new Headers(h)
  assert.equal(clientLabel(headers({ 'x-client': 'my-app/2.0' })), 'my-app/2.0')
  assert.equal(clientLabel(headers({ 'user-agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit' })), 'Mozilla')
  assert.equal(clientLabel(headers({ 'user-agent': 'curl/8.7.1' })), 'curl')
  assert.equal(clientLabel(headers({})), 'unknown')
})

test('the client label cannot be used to inject log noise or grow without bound', () => {
  const headers = (h: Record<string, string>) => new Headers(h)
  assert.equal(clientLabel(headers({ 'x-client': 'evil"}{"severity":"ERROR"' })), 'evil severity ERROR')
  assert.ok(clientLabel(headers({ 'x-client': 'a'.repeat(500) })).length <= 60)
  assert.equal(clientLabel(headers({ 'x-client': '   ' })), 'unknown')
})

test('the documentation tells integrators how to identify their app', () => {
  const doc = buildOpenApiDocument('https://x') as any
  const header = doc.paths['/v1/problems/{contestId}/{index}/hints'].get.parameters.find((p: any) => p.name === 'X-Client')
  assert.equal(header.in, 'header')
  assert.equal(header.required, false)
})

test('a browser app can name itself in the url, since a custom header would need a preflight', () => {
  const headers = (h: Record<string, string>) => new Headers(h)
  assert.equal(clientLabel(headers({}), 'leekcf-ratings/3.0.1'), 'leekcf-ratings/3.0.1')
  assert.equal(clientLabel(headers({ 'user-agent': 'Mozilla/5.0 (X11)' }), 'leekcf-ratings/3.0.1'), 'leekcf-ratings/3.0.1')
  assert.equal(clientLabel(headers({ 'x-client': 'from-header/1' }), 'from-url/2'), 'from-header/1')
  assert.equal(clientLabel(headers({ 'user-agent': 'curl/8.7.1' }), '   '), 'curl')
  assert.equal(clientLabel(headers({}), 'evil"}{"severity":"ERROR"'), 'evil severity ERROR')
  assert.ok(clientLabel(headers({}), 'a'.repeat(500)).length <= 60)
})

test('the ?client= label reaches the logs and the statistics, whether or not the answer came from the edge cache', async () => {
  const { worker, logs, cache } = setup()
  const points: any[] = []
  const withAnalytics = { ...env, ANALYTICS: { writeDataPoint: (p: any) => points.push(p) } } as any
  const c = ctx()
  await worker.fetch(get('/v1/problems/1944/C/hints?client=leekcf-ratings%2F3.0.1'), withAnalytics, c)
  await c.settle()
  await worker.fetch(get('/v1/problems/1944/C/hints?client=leekcf-ratings%2F3.0.1'), withAnalytics, ctx()) // now a cache hit
  const requests = logs.filter((e) => e.message === 'request')
  assert.deepEqual(requests.map((e) => e.client), ['leekcf-ratings/3.0.1', 'leekcf-ratings/3.0.1'])
  assert.equal(requests[1].cache, 'hit')
  assert.deepEqual(points.map((p) => p.blobs[2]), ['leekcf-ratings/3.0.1', 'leekcf-ratings/3.0.1'])
  assert.equal(cache.store.size, 1)
})

test('the edge cache ignores the query string, so ?client= and made-up parameters share one entry', async () => {
  const { worker, calls, cache } = setup()
  const c = ctx()
  await worker.fetch(get('/v1/problems/1944/C/hints?client=ext%2F1.0'), env, c)
  await c.settle()
  assert.deepEqual([...cache.store.keys()], ['https://hints.example.org/v1/problems/1944/C/hints'])
  const other = await worker.fetch(get('/v1/problems/1944/C/hints?client=site%2F2&cachebust=123'), env, ctx())
  assert.equal(other.status, 200)
  assert.equal(calls.length, 1)
})

test('the documentation lists the client query parameter next to the header', () => {
  const doc = buildOpenApiDocument('https://x') as any
  const parameters = doc.paths['/v1/problems/{contestId}/{index}/hints'].get.parameters
  const query = parameters.find((p: any) => p.name === 'client')
  assert.equal(query.in, 'query')
  assert.equal(query.required, false)
  assert.equal(query.schema.maxLength, 60)
})

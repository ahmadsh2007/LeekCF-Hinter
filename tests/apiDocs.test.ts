import { test } from 'node:test'
import assert from 'node:assert/strict'
import { buildOpenApiDocument } from '../src/api/docs/openapi.ts'
import { renderDocsHtml } from '../src/api/docs/renderDocs.ts'
import { createRouter } from '../src/api/routes/router.ts'
import { toHintsPayload } from '../src/api/controllers/hintsController.ts'
import { RateLimiter } from '../src/api/middlewares/rateLimiter.ts'
import { TtlCache } from '../src/api/middlewares/ttlCache.ts'
import type { HintRow, HintsRepository } from '../src/api/types.ts'
import type { HintsPayload } from '../src/api/controllers/hintsController.ts'

const doc = buildOpenApiDocument('https://hints.example.org') as any

const sampleRows: HintRow[] = [1, 2, 3].map((level) => ({
  problem_id: '1944_C', contest_id: 1944, index: 'C', name: 'MEX Game 1', rating: 1500, tags: ['games'],
  hints_problem_id: '1943_A', hint_level: level, content: `Hint ${level}`, grounded_in_tutorial: true,
  generated_at: '2024-01-02T00:00:00+00:00',
}))

test('the document describes the hints endpoint with its parameters and every status it can return', () => {
  assert.equal(doc.openapi, '3.1.0')
  assert.equal(doc.servers[0].url, 'https://hints.example.org')
  const operation = doc.paths['/v1/problems/{contestId}/{index}/hints'].get
  assert.deepEqual(operation.parameters.map((p: any) => p.name), ['contestId', 'index'])
  assert.ok(operation.parameters.every((p: any) => p.in === 'path' && p.required === true))
  for (const status of ['200', '400', '404', '429', '503']) assert.ok(operation.responses[status], status)
  assert.ok(operation.responses['429'].headers['Retry-After'])
  assert.ok(doc.paths['/v1/health'].get)
})

test('the documented response has exactly the fields the api returns (contract)', () => {
  const payload = toHintsPayload(sampleRows) as HintsPayload
  const schema = doc.components.schemas.HintsResponse
  assert.deepEqual(Object.keys(schema.properties).sort(), Object.keys(payload).sort())
  assert.deepEqual([...schema.required].sort(), Object.keys(payload).sort())
  assert.deepEqual(Object.keys(doc.components.schemas.Problem.properties).sort(), Object.keys(payload.problem).sort())
  assert.deepEqual(Object.keys(doc.components.schemas.Hint.properties).sort(), Object.keys(payload.hints[0]).sort())
})

test('the documented example is itself a valid response shape', () => {
  const example = doc.paths['/v1/problems/{contestId}/{index}/hints'].get.responses['200'].content['application/json'].example
  const payload = toHintsPayload(sampleRows) as HintsPayload
  assert.deepEqual(Object.keys(example).sort(), Object.keys(payload).sort())
  assert.deepEqual(Object.keys(example.problem).sort(), Object.keys(payload.problem).sort())
  assert.ok(example.hints.length >= 2 && example.hints.length <= 5)
  assert.deepEqual(example.hints.map((h: any) => h.level), example.hints.map((_: any, i: number) => i + 1))
})

test('every error code the router can send is listed in the document', async () => {
  const repository: HintsRepository = { async findHints(contestId) { if (contestId === 503) throw new Error('db'); return contestId === 404 ? [] : sampleRows } }
  const route = createRouter({ repository, limiter: new RateLimiter(3, 0.001), cache: new TtlCache<HintsPayload | null>(1000, 10), log: () => {} })
  const sent = new Set<string>()
  for (const [method, path] of [['GET', '/v1/problems/abc/A/hints'], ['GET', '/v1/problems/404/A/hints'], ['GET', '/v1/problems/503/A/hints'], ['GET', '/v1/problems/1/A/hints'], ['POST', '/v1/health']]) {
    const response = await route({ method, path, ip: '9.9.9.9' })
    const code = JSON.parse(response.body)?.error?.code
    if (code) sent.add(code)
  }
  const documented = doc.components.schemas.Error.properties.error.properties.code.enum
  for (const code of sent) assert.ok(documented.includes(code), `${code} is not documented`)
  assert.ok(sent.size >= 4)
})

test('the docs page shows the endpoint, an example and the rules, as safe html', () => {
  const html = renderDocsHtml(doc)
  for (const fragment of ['/v1/problems/{contestId}/{index}/hints', 'curl', 'Retry-After', 'not_found', 'rate limit']) {
    assert.ok(html.toLowerCase().includes(fragment.toLowerCase()), fragment)
  }
  assert.match(html, /^<!doctype html>/i)
})

test('text from the document is escaped in the html', () => {
  const hostile = buildOpenApiDocument('https://x.example') as any
  hostile.info.description = '<script>alert(1)</script> & "quotes"'
  const html = renderDocsHtml(hostile)
  assert.ok(!html.includes('<script>'))
  assert.ok(html.includes('&lt;script&gt;'))
})

function routerWithSpy() {
  const calls: unknown[] = []
  const repository: HintsRepository = { async findHints() { calls.push(1); return sampleRows } }
  const route = createRouter({
    repository, limiter: new RateLimiter(100, 1), cache: new TtlCache<HintsPayload | null>(1000, 10),
    log: () => {}, publicBaseUrl: 'https://hints.example.org',
  })
  return { route, calls }
}

test('the router serves the openapi document and the docs page without touching the database', async () => {
  const { route, calls } = routerWithSpy()
  const spec = await route({ method: 'GET', path: '/v1/openapi.json', ip: '1.1.1.1' })
  assert.equal(spec.status, 200)
  assert.match(spec.headers['Content-Type'], /application\/json/)
  assert.equal(JSON.parse(spec.body).servers[0].url, 'https://hints.example.org')
  assert.equal(spec.headers['Access-Control-Allow-Origin'], '*')

  for (const path of ['/', '/v1/docs']) {
    const page = await route({ method: 'GET', path, ip: '1.1.1.1' })
    assert.equal(page.status, 200, path)
    assert.match(page.headers['Content-Type'], /text\/html/)
    assert.match(page.headers['Content-Security-Policy'], /default-src 'none'/)
    assert.ok(page.body.includes('https://hints.example.org'))
  }
  assert.deepEqual(calls, [])
})

test('the docs routes are read-only like everything else', async () => {
  const { route } = routerWithSpy()
  assert.equal((await route({ method: 'POST', path: '/v1/docs', ip: '1.1.1.1' })).status, 405)
  const head = await route({ method: 'HEAD', path: '/v1/openapi.json', ip: '1.1.1.1' })
  assert.equal(head.status, 200)
  assert.equal(head.body, '')
})

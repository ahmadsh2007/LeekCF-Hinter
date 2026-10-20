import type { ApiRequest, ApiResponse, HintsRepository } from '../types.ts'
import { toHintsPayload, type HintsPayload } from '../controllers/hintsController.ts'
import type { RateLimiter } from '../middlewares/rateLimiter.ts'
import type { TtlCache } from '../middlewares/ttlCache.ts'
import { buildOpenApiDocument } from '../docs/openapi.ts'
import { renderDocsHtml } from '../docs/renderDocs.ts'

export interface RouterDeps {
  repository: HintsRepository
  limiter: RateLimiter
  cache: TtlCache<HintsPayload | null>
  now?: () => number
  log?: (entry: Record<string, unknown>) => void
  positiveTtlMs?: number // how long found hints stay in memory
  negativeTtlMs?: number // how long "no hints (yet)" stays in memory
  publicBaseUrl?: string // shown in the documentation (PUBLIC_BASE_URL)
}

const ALLOWED_METHODS = 'GET, HEAD, OPTIONS'
const HINTS_PATH = /^\/v1\/problems\/([^/]+)\/([^/]+)\/hints\/?$/
const CONTEST_ID = /^\d{1,7}$/
const PROBLEM_INDEX = /^[A-Za-z][0-9]{0,2}$/

const BASE_HEADERS = {
  'Content-Type': 'application/json; charset=utf-8',
  'X-Content-Type-Options': 'nosniff',
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Expose-Headers': 'Retry-After', // lets a browser app read how long to wait after a 429
}
const FOUND_CACHE_CONTROL = 'public, max-age=300, s-maxage=3600, stale-while-revalidate=86400'
const NOT_FOUND_CACHE_CONTROL = 'public, max-age=60'
const DOCS_CACHE_CONTROL = 'public, max-age=3600'

function json(status: number, payload: unknown, cacheControl = 'no-store', extra: Record<string, string> = {}): ApiResponse {
  return { status, headers: { ...BASE_HEADERS, 'Cache-Control': cacheControl, ...extra }, body: JSON.stringify(payload) }
}

function errorResponse(status: number, code: string, message: string, extra: Record<string, string> = {}, cacheControl = 'no-store'): ApiResponse {
  return json(status, { error: { code, message } }, cacheControl, extra)
}

export function createRouter(deps: RouterDeps) {
  const now = deps.now ?? Date.now
  const log = deps.log ?? ((entry: Record<string, unknown>) => console.log(JSON.stringify(entry)))
  const positiveTtlMs = deps.positiveTtlMs ?? 10 * 60_000
  const negativeTtlMs = deps.negativeTtlMs ?? 60_000
  const inFlight = new Map<string, Promise<HintsPayload | null>>()
  const openApiDocument = buildOpenApiDocument(deps.publicBaseUrl ?? 'https://YOUR-API-HOST')
  const docsHtml = renderDocsHtml(openApiDocument)

  async function lookup(contestId: number, index: string): Promise<HintsPayload | null> {
    const key = `${contestId}_${index}`
    const cached = deps.cache.get(key)
    if (cached.hit) return cached.value

    // Many requests for the same cold problem share one database call.
    let pending = inFlight.get(key)
    if (!pending) {
      pending = deps.repository.findHints(contestId, index).then((rows) => {
        const payload = toHintsPayload(rows)
        deps.cache.set(key, payload, payload ? positiveTtlMs : negativeTtlMs)
        return payload
      })
      inFlight.set(key, pending)
      pending.then(() => inFlight.delete(key), () => inFlight.delete(key))
    }
    return pending
  }

  async function handle(request: ApiRequest): Promise<{ route: string; response: ApiResponse }> {
    const method = request.method.toUpperCase()

    if (method === 'OPTIONS') {
      return {
        route: 'preflight',
        response: {
          status: 204,
          headers: { ...BASE_HEADERS, 'Access-Control-Allow-Methods': ALLOWED_METHODS, 'Access-Control-Allow-Headers': 'X-Client', 'Access-Control-Max-Age': '86400' },
          body: '',
        },
      }
    }

    if (request.path === '/v1/health') {
      if (method !== 'GET' && method !== 'HEAD') {
        return { route: 'health', response: errorResponse(405, 'method_not_allowed', 'Only GET is supported.', { Allow: ALLOWED_METHODS }) }
      }
      return { route: 'health', response: json(200, { status: 'ok' }) }
    }

    const decision = deps.limiter.take(request.ip)
    if (!decision.allowed) {
      return {
        route: 'rate_limited',
        response: errorResponse(429, 'rate_limited', 'Too many requests. Please slow down.', { 'Retry-After': String(decision.retryAfterSeconds) }),
      }
    }

    if (request.path === '/' || request.path === '/v1/docs' || request.path === '/v1/openapi.json') {
      if (method !== 'GET' && method !== 'HEAD') {
        return { route: 'docs', response: errorResponse(405, 'method_not_allowed', 'Only GET is supported.', { Allow: ALLOWED_METHODS }) }
      }
      if (request.path === '/v1/openapi.json') {
        return { route: 'docs', response: json(200, openApiDocument, DOCS_CACHE_CONTROL) }
      }
      return {
        route: 'docs',
        response: {
          status: 200,
          headers: {
            'Content-Type': 'text/html; charset=utf-8',
            'X-Content-Type-Options': 'nosniff',
            'Cache-Control': DOCS_CACHE_CONTROL,
            'Content-Security-Policy': "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'",
          },
          body: docsHtml,
        },
      }
    }

    const match = HINTS_PATH.exec(request.path)
    if (!match) {
      return { route: 'other', response: errorResponse(404, 'not_found', 'No such endpoint.') }
    }
    if (method !== 'GET' && method !== 'HEAD') {
      return { route: 'hints', response: errorResponse(405, 'method_not_allowed', 'Only GET is supported.', { Allow: ALLOWED_METHODS }) }
    }

    const [, contestSegment, indexSegment] = match
    if (!CONTEST_ID.test(contestSegment) || !PROBLEM_INDEX.test(indexSegment)) {
      return { route: 'hints', response: errorResponse(400, 'invalid_problem', 'Use /v1/problems/{contestId}/{index}/hints, for example /v1/problems/1944/C/hints.') }
    }

    try {
      const payload = await lookup(Number(contestSegment), indexSegment.toUpperCase())
      if (!payload) {
        // The same answer whether the problem is unknown, still being processed, or its contest is not over.
        return { route: 'hints', response: errorResponse(404, 'not_found', 'No hints are available for this problem.', {}, NOT_FOUND_CACHE_CONTROL) }
      }
      return { route: 'hints', response: json(200, payload, FOUND_CACHE_CONTROL) }
    } catch (error) {
      log({ severity: 'ERROR', message: `Looking up hints failed: ${error instanceof Error ? error.message : String(error)}` })
      return { route: 'hints', response: errorResponse(503, 'unavailable', 'The service is temporarily unavailable. Please try again shortly.') }
    }
  }

  return async function route(request: ApiRequest): Promise<ApiResponse> {
    const startedAt = now()
    const { route: routeName, response } = await handle(request)
    log({ severity: 'INFO', message: 'request', route: routeName, method: request.method, status: response.status, durationMs: now() - startedAt, client: request.client ?? 'unknown' })
    return request.method.toUpperCase() === 'HEAD' ? { ...response, body: '' } : response
  }
}

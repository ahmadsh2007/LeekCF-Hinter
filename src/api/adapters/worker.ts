import { createRouter } from '../routes/router.ts'
import { createSupabaseHintsRepository } from '../controllers/supabaseHintsRepository.ts'
import { RateLimiter } from '../middlewares/rateLimiter.ts'
import { TtlCache } from '../middlewares/ttlCache.ts'
import { assertPublicKey } from '../middlewares/keySafety.ts'
import { clientLabel } from '../middlewares/clientLabel.ts'
import type { HintsPayload } from '../controllers/hintsController.ts'
import type { HintsRepository } from '../types.ts'

// The same API on Cloudflare Workers: the router is unchanged, this file only translates between Workers' Request /
// Response and the router's plain objects, adds Cloudflare's edge cache in front, and reports usage.
// Configuration (wrangler secrets / variables): SUPABASE_DATABASE_URL, SUPABASE_PUBLISHABLE_KEY, PUBLIC_BASE_URL.
// Optional: an Analytics Engine dataset bound as ANALYTICS.

export interface WorkerEnv {
  SUPABASE_DATABASE_URL?: string
  SUPABASE_PUBLISHABLE_KEY?: string
  PUBLIC_BASE_URL?: string
  ANALYTICS?: { writeDataPoint(point: { blobs: string[]; doubles: number[]; indexes?: string[] }): void }
}

interface EdgeCache {
  match(request: Request): Promise<Response | undefined>
  put(request: Request, response: Response): Promise<void>
}

export interface WorkerDeps {
  repository?: HintsRepository
  cache?: EdgeCache
  capacity?: number // requests a client address may burst; refills at capacity per minute (per isolate)
  log?: (entry: Record<string, unknown>) => void
}

const CACHEABLE_STATUSES = [200, 404]

export function createWorker(deps: WorkerDeps = {}) {
  const log = deps.log ?? ((entry: Record<string, unknown>) => console.log(JSON.stringify(entry)))
  let built: { signature: string; route: ReturnType<typeof createRouter> } | undefined

  function routerFor(env: WorkerEnv) {
    const signature = `${env.SUPABASE_DATABASE_URL}|${env.SUPABASE_PUBLISHABLE_KEY}|${env.PUBLIC_BASE_URL}`
    if (built?.signature === signature) return built.route

    let repository = deps.repository
    if (!repository) {
      if (!env.SUPABASE_DATABASE_URL) throw new Error('SUPABASE_DATABASE_URL is not set.')
      assertPublicKey(env.SUPABASE_PUBLISHABLE_KEY)
      repository = createSupabaseHintsRepository(env.SUPABASE_DATABASE_URL, env.SUPABASE_PUBLISHABLE_KEY as string)
    }
    const capacity = deps.capacity ?? 60
    const route = createRouter({
      repository,
      limiter: new RateLimiter(capacity, capacity / 60),
      cache: new TtlCache<HintsPayload | null>(10 * 60_000, 2_000),
      publicBaseUrl: env.PUBLIC_BASE_URL,
      log: (entry) => {
        log(entry)
        if (entry.message === 'request') recordAnalytics(env, String(entry.route), Number(entry.status), String(entry.client ?? 'unknown'), Number(entry.durationMs ?? 0), 0)
      },
    })
    built = { signature, route }
    return route
  }

  function recordAnalytics(env: WorkerEnv, route: string, status: number, client: string, durationMs: number, cacheHit: number) {
    try {
      env.ANALYTICS?.writeDataPoint({ blobs: [route, String(status), client], doubles: [durationMs, cacheHit] })
    } catch (error) {
      log({ severity: 'WARNING', message: `Analytics write failed: ${error instanceof Error ? error.message : String(error)}` })
    }
  }

  return {
    async fetch(request: Request, env: WorkerEnv, ctx: { waitUntil(promise: Promise<unknown>): void }): Promise<Response> {
      const startedAt = Date.now()
      const url = new URL(request.url)
      const client = clientLabel(request.headers, url.searchParams.get('client'))
      const cache = deps.cache ?? ((globalThis as any).caches?.default as EdgeCache | undefined)
      const cacheable = request.method === 'GET' && cache !== undefined
      // The answer does not depend on the query string, so key the cache on the path alone: ?client= must not give
      // every app its own entry, and made-up parameters must not be a way around the cache.
      const cacheKey = new Request(url.origin + url.pathname)

      if (cacheable) {
        const hit = await cache.match(cacheKey)
        if (hit) {
          // Served by Cloudflare's cache without running the router: still counted.
          const durationMs = Date.now() - startedAt
          log({ severity: 'INFO', message: 'request', route: 'hints', method: 'GET', status: hit.status, durationMs, client, cache: 'hit' })
          recordAnalytics(env, 'hints', hit.status, client, durationMs, 1)
          return hit
        }
      }

      let route: ReturnType<typeof createRouter>
      try {
        route = routerFor(env)
      } catch (error) {
        log({ severity: 'ERROR', message: `Worker is misconfigured: ${error instanceof Error ? error.message : String(error)}` })
        return Response.json({ error: { code: 'internal', message: 'The service is not configured correctly.' } }, { status: 500, headers: { 'Cache-Control': 'no-store' } })
      }

      const result = await route({
        method: request.method,
        path: url.pathname,
        ip: request.headers.get('cf-connecting-ip') ?? 'unknown',
        client,
      })
      const response = new Response(result.body === '' ? null : result.body, { status: result.status, headers: result.headers })

      if (cacheable && CACHEABLE_STATUSES.includes(result.status) && /public/.test(result.headers['Cache-Control'] ?? '')) {
        ctx.waitUntil(cache.put(cacheKey, response.clone()))
      }
      return response
    },
  }
}

export default createWorker()

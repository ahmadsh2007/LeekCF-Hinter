import http from 'node:http'
import { createApp } from './app.ts'
import { createRouter } from './routes/router.ts'
import { createSupabaseHintsRepository } from './controllers/supabaseHintsRepository.ts'
import { RateLimiter } from './middlewares/rateLimiter.ts'
import { TtlCache } from './middlewares/ttlCache.ts'
import { assertPublicKey } from './middlewares/keySafety.ts'
import type { HintsPayload } from './controllers/hintsController.ts'

// Configuration (environment variables):
//   SUPABASE_DATABASE_URL        project URL
//   SUPABASE_PUBLISHABLE_KEY     the publishable (anon) key. NOT the secret key; the server refuses that.
//   PORT                         default 8080 (Cloud Run sets it)
//   PUBLIC_BASE_URL              the address people use, shown in the documentation (default: a placeholder)
//   RATE_LIMIT_PER_MINUTE        per client address and instance, default 60 (also the burst size)
const url = process.env.SUPABASE_DATABASE_URL
const key = process.env.SUPABASE_PUBLISHABLE_KEY
if (!url) throw new Error('SUPABASE_DATABASE_URL is not set.')
assertPublicKey(key)

const perMinute = Number(process.env.RATE_LIMIT_PER_MINUTE ?? 60)
if (!Number.isFinite(perMinute) || perMinute <= 0) throw new Error('RATE_LIMIT_PER_MINUTE must be a positive number.')
const port = Number(process.env.PORT ?? 8080)

const route = createRouter({
  repository: createSupabaseHintsRepository(url, key as string),
  limiter: new RateLimiter(perMinute, perMinute / 60),
  cache: new TtlCache<HintsPayload | null>(10 * 60_000, 5_000),
  publicBaseUrl: process.env.PUBLIC_BASE_URL,
})

const server = http.createServer(createApp(route))
server.requestTimeout = 10_000
server.headersTimeout = 10_000
server.keepAliveTimeout = 65_000 // above the 60 s idle timeout of Google's load balancers

server.listen(port, () => {
  console.log(JSON.stringify({ severity: 'INFO', message: `Hint API listening on port ${port}` }))
})

// Cloud Run sends SIGTERM before stopping an instance: finish in-flight requests, then exit.
process.on('SIGTERM', () => {
  server.close(() => process.exit(0))
})

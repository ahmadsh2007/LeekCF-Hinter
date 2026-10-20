import type { IncomingMessage, RequestListener, ServerResponse } from 'node:http'
import type { ApiRequest, ApiResponse } from './types.ts'
import { clientIp } from './middlewares/clientIp.ts'
import { clientLabel } from './middlewares/clientLabel.ts'

// The only place that knows about node:http. Everything else works on plain request/response objects.
export function createApp(route: (request: ApiRequest) => Promise<ApiResponse>): RequestListener {
  return async (req: IncomingMessage, res: ServerResponse) => {
    try {
      const forwardedFor = req.headers['x-forwarded-for']
      const request: ApiRequest = {
        method: req.method ?? 'GET',
        // Split by hand: new URL() would treat "//host/path" as a host.
        path: (req.url ?? '/').split('?')[0],
        ip: clientIp(Array.isArray(forwardedFor) ? forwardedFor.join(',') : forwardedFor, req.socket.remoteAddress),
        client: clientLabel(
          { get: (name) => { const value = req.headers[name]; return Array.isArray(value) ? value.join(',') : (value ?? null) } },
          new URLSearchParams((req.url ?? '').split('?')[1] ?? '').get('client'),
        ),
      }
      const response = await route(request)
      res.writeHead(response.status, response.headers)
      res.end(response.body)
    } catch (error) {
      console.error(JSON.stringify({ severity: 'ERROR', message: `Unhandled error: ${error instanceof Error ? error.message : String(error)}` }))
      if (!res.headersSent) {
        res.writeHead(500, { 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store' })
      }
      res.end(JSON.stringify({ error: { code: 'internal', message: 'Something went wrong.' } }))
    }
  }
}

const MAX_LENGTH = 60

interface HeaderReader {
  get(name: string): string | null
}

// A short, safe name for whoever is calling, for usage statistics per app. Integrators are asked to send
// "X-Client: my-app/1.0"; browser apps can use "?client=my-app/1.0" instead, which needs no preflight request.
// The header wins when both are given; with neither, the first token of the User-Agent is used. Anything outside a
// small alphabet is replaced so the value can never inject log lines, and it is cut short so it cannot grow without
// bound. It is self-declared, so it is a convenience for statistics, never a means of identification or access.
export function clientLabel(headers: HeaderReader, fromUrl?: string | null): string {
  const declared = headers.get('x-client')
  const named = [declared, fromUrl].find((value) => value && value.trim())
  const raw = named ?? (headers.get('user-agent') ?? '').trim().split(/[/\s]/)[0]
  const cleaned = raw.replace(/[^A-Za-z0-9._/@ -]+/g, ' ').replace(/\s+/g, ' ').trim().slice(0, MAX_LENGTH).trim()
  return cleaned || 'unknown'
}

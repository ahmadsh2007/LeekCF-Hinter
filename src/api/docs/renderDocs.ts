// Renders the OpenAPI document as one self-contained page: no scripts, no external files.
const escapeHtml = (value: unknown): string =>
  String(value).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;')

const STYLE = `
:root { --bg:#ffffff; --fg:#1b1f24; --muted:#59636e; --line:#d8dee4; --code:#f4f6f8; --accent:#0b5fff; }
@media (prefers-color-scheme: dark) { :root { --bg:#0f1318; --fg:#e6eaf0; --muted:#9aa4b0; --line:#2a323c; --code:#171d25; --accent:#6ea8ff; } }
body { background:var(--bg); color:var(--fg); font:16px/1.55 system-ui, sans-serif; margin:0; }
main { max-width:52rem; margin:0 auto; padding:2rem 1rem 4rem; }
h1 { font-size:1.8rem; margin:.2rem 0 .6rem; } h2 { margin-top:2.2rem; border-bottom:1px solid var(--line); padding-bottom:.3rem; }
code, pre { background:var(--code); border-radius:6px; font:14px ui-monospace, monospace; }
code { padding:.1rem .3rem; } pre { padding:.8rem 1rem; overflow-x:auto; }
table { border-collapse:collapse; width:100%; } th, td { text-align:left; border-bottom:1px solid var(--line); padding:.4rem .5rem; vertical-align:top; }
.muted { color:var(--muted); } .method { color:var(--accent); font-weight:600; }
`

type Json = any

function exampleUrl(base: string, path: string, parameters: Json[]): string {
  return base + path.replace(/\{(\w+)\}/g, (_, name) => String(parameters.find((p) => p.name === name)?.example ?? name))
}

export function renderDocsHtml(doc: Json): string {
  const base: string = doc.servers?.[0]?.url ?? ''
  const sections: string[] = []

  for (const [path, item] of Object.entries<Json>(doc.paths)) {
    for (const [method, operation] of Object.entries<Json>(item)) {
      const parameters: Json[] = operation.parameters ?? []
      const okResponse = operation.responses?.['200']?.content?.['application/json']
      sections.push(`
<h2><span class="method">${escapeHtml(method.toUpperCase())}</span> <code>${escapeHtml(path)}</code></h2>
<p><strong>${escapeHtml(operation.summary)}</strong></p>
${operation.description ? `<p>${escapeHtml(operation.description)}</p>` : ''}
${parameters.length ? `<table><tr><th>Parameter</th><th>Description</th><th>Example</th></tr>${parameters
        .map((p) => `<tr><td><code>${escapeHtml(p.name)}</code></td><td>${escapeHtml(p.description)}</td><td><code>${escapeHtml(p.example)}</code></td></tr>`)
        .join('')}</table>` : ''}
<p>Try it:</p>
<pre>curl ${escapeHtml(exampleUrl(base, path, parameters))}</pre>
${okResponse?.example ? `<p>Response <code>200</code>:</p><pre>${escapeHtml(JSON.stringify(okResponse.example, null, 2))}</pre>` : ''}
<table><tr><th>Status</th><th>Meaning</th></tr>${Object.entries<Json>(operation.responses)
        .map(([status, response]) => `<tr><td><code>${escapeHtml(status)}</code></td><td>${escapeHtml(response.description)}</td></tr>`)
        .join('')}</table>`)
    }
  }

  const codes: string[] = doc.components?.schemas?.Error?.properties?.error?.properties?.code?.enum ?? []
  return `<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>${escapeHtml(doc.info.title)}</title><style>${STYLE}</style></head>
<body><main>
<h1>${escapeHtml(doc.info.title)}</h1>
<p class="muted">Version ${escapeHtml(doc.info.version)} · base URL <code>${escapeHtml(base)}</code> · <a href="/v1/openapi.json">OpenAPI document</a></p>
<p>${escapeHtml(doc.info.description)}</p>
${sections.join('\n')}
<h2>Errors</h2>
<p>Errors are JSON: <code>{"error": {"code": "...", "message": "..."}}</code>. Codes: ${codes.map((code) => `<code>${escapeHtml(code)}</code>`).join(', ')}.</p>
<h2>Being a good client</h2>
<ul>
<li>Stay under the rate limit (HTTP 429 carries a <code>Retry-After</code> header) and cache answers; hints rarely change.</li>
<li>Show hints one at a time so readers are not spoiled by accident.</li>
<li>Link back to the problem on codeforces.com; this API does not serve statements or editorials.</li>
</ul>
</main></body></html>`
}

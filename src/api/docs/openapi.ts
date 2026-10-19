// The single description of the public API. It is served at /v1/openapi.json and rendered at /v1/docs, and a test
// compares it with what the controller really returns, so the documentation cannot drift from the code.
export function buildOpenApiDocument(publicBaseUrl: string): Record<string, unknown> {
  const exampleResponse = {
    problem: { id: '1944_C', contestId: 1944, index: 'C', name: 'MEX Game 1', rating: 1500, tags: ['games', 'greedy'] },
    duplicateOf: '1943_A',
    hints: [
      { level: 1, content: 'Think about which numbers Alice can always keep, whatever Bob removes.' },
      { level: 2, content: 'A value that appears at least twice can never be taken away from Alice completely.' },
      { level: 3, content: 'Only values that appear once matter. Look at the smallest values with count $0$ and $1$.' },
    ],
    groundedInTutorial: true,
    generatedAt: '2026-10-19T12:00:00+00:00',
  }

  const errorResponse = (description: string) => ({
    description,
    content: { 'application/json': { schema: { $ref: '#/components/schemas/Error' } } },
  })

  return {
    openapi: '3.1.0',
    info: {
      title: 'LeekCF Hinter API',
      version: '1.0.0',
      description:
        'Progressive hints (2 to 5 per problem, gentlest first) for Codeforces problems. Free, read-only, no API key. ' +
        'Hints are served only after a contest has ended, plus a 2-hour margin for system tests, so they never spoil a ' +
        'running round. Problem statements and editorials are not served here: use the problem link on codeforces.com. ' +
        'The hints are written by an AI model from the statement and, when one exists, the official editorial. They can ' +
        'be wrong, so check them against the editorial. Each client address may make about 60 requests per minute ' +
        '(HTTP 429 with Retry-After beyond that). Answers are cacheable; please cache them on your side.',
    },
    servers: [{ url: publicBaseUrl }],
    paths: {
      '/v1/problems/{contestId}/{index}/hints': {
        get: {
          operationId: 'getProblemHints',
          summary: 'Get the hints of one problem',
          description:
            'Returns every hint level of the problem, gentlest first. Reveal them one at a time in your interface so ' +
            'the reader is not spoiled by accident. A problem Codeforces lists in two divisions resolves to the same ' +
            'hints (see duplicateOf).',
          parameters: [
            {
              name: 'contestId', in: 'path', required: true, description: 'The Codeforces contest id.',
              schema: { type: 'integer', minimum: 1, maximum: 9999999 }, example: 1944,
            },
            {
              name: 'index', in: 'path', required: true,
              description: 'The problem letter, with a digit for split problems (A, B1, D2). Case-insensitive.',
              schema: { type: 'string', pattern: '^[A-Za-z][0-9]{0,2}$' }, example: 'C',
            },
          ],
          responses: {
            '200': {
              description: 'The hints.',
              headers: { 'Cache-Control': { description: 'Public, cacheable for 5 minutes (CDN: 1 hour).', schema: { type: 'string' } } },
              content: { 'application/json': { schema: { $ref: '#/components/schemas/HintsResponse' }, example: exampleResponse } },
            },
            '400': errorResponse('The contest id or index is not a plausible Codeforces problem id (invalid_problem).'),
            '404': errorResponse(
              'No hints are available for this problem (not_found). The same answer is given whether the problem is unknown, ' +
                'not processed yet, or its contest is not over, so try again later.',
            ),
            '429': {
              ...errorResponse('Too many requests (rate_limited). Wait Retry-After seconds.'),
              headers: { 'Retry-After': { description: 'Seconds to wait before the next request.', schema: { type: 'integer' } } },
            },
            '503': errorResponse('The service is temporarily unavailable (unavailable). Try again shortly.'),
          },
        },
      },
      '/v1/health': {
        get: {
          operationId: 'getHealth',
          summary: 'Liveness check',
          responses: {
            '200': {
              description: 'The service is up.',
              content: { 'application/json': { schema: { type: 'object', properties: { status: { type: 'string', const: 'ok' } }, required: ['status'] }, example: { status: 'ok' } } },
            },
          },
        },
      },
    },
    components: {
      schemas: {
        HintsResponse: {
          type: 'object',
          properties: {
            problem: { $ref: '#/components/schemas/Problem' },
            duplicateOf: { type: ['string', 'null'], description: 'When this problem is the same as another one (Div. 1 and Div. 2 versions), the id of the problem that holds the hints; otherwise null.' },
            hints: { type: 'array', minItems: 2, maxItems: 5, items: { $ref: '#/components/schemas/Hint' }, description: 'Gentlest first; the last hint is the complete solution.' },
            groundedInTutorial: { type: 'boolean', description: 'True when the hints were written with the official editorial at hand; false when the model had only the statement.' },
            generatedAt: { type: 'string', format: 'date-time' },
          },
          required: ['problem', 'duplicateOf', 'hints', 'groundedInTutorial', 'generatedAt'],
        },
        Problem: {
          type: 'object',
          properties: {
            id: { type: 'string', description: 'contestId_index, e.g. 1944_C' },
            contestId: { type: 'integer' },
            index: { type: 'string' },
            name: { type: 'string' },
            rating: { type: ['integer', 'null'], description: 'Codeforces difficulty rating; null when unrated.' },
            tags: { type: 'array', items: { type: 'string' } },
          },
          required: ['id', 'contestId', 'index', 'name', 'rating', 'tags'],
        },
        Hint: {
          type: 'object',
          properties: {
            level: { type: 'integer', minimum: 1, maximum: 5 },
            content: { type: 'string', description: 'Markdown; math is written between single dollar signs.' },
          },
          required: ['level', 'content'],
        },
        Error: {
          type: 'object',
          properties: {
            error: {
              type: 'object',
              properties: {
                code: { type: 'string', enum: ['invalid_problem', 'not_found', 'rate_limited', 'unavailable', 'method_not_allowed'] },
                message: { type: 'string' },
              },
              required: ['code', 'message'],
            },
          },
          required: ['error'],
        },
      },
    },
  }
}

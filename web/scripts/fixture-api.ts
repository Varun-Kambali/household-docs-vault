// The built app (dist/) on 127.0.0.1:4173 with a stand-in for the API, for the accessibility
// check and for looking at the screens without the vault. The replies are the ones
// scripts/record_fixtures.py recorded from the synthetic dev vault; nothing here reads a real
// document or calls a model.
//
// - GET /v1/needs-a-look answers the recorded list (a locked PDF and two copies), one file, three
//   files that ask the same question, an empty list, or a refusal, by scenario.
// - GET /v1/activity, /v1/inbox/progress, /v1/secrets/status and /v1/items/<id>/pages/0.png answer
//   the recorded replies; what the Inbox posts is answered with a plain success, except Unlock,
//   which says the password did not open the file.
// - GET /healthz answers the recorded health reply.
// - POST /v1/search answers the recorded quick, answer, no-answer and model-off replies; a prompt
//   with "anil" in it is the one that gets no answer.
// - POST /v1/search/list answers the recorded lists: the area lists (an empty one for rent), the
//   list a change makes, and the list a linked address names. A full search for a prompt with
//   "expire" in it reads as a list; with "diwali" too, a list with a part it could not read.
// - GET /v1/people, /v1/documents/<doc-photo|doc-pdf>, its lines and its page image answer the
//   recorded ones; Show in folder answers that it is not on the Mac.
// - /__scenario/<waiting|one|group|empty|down|modeloff>?to=/path picks the scenario, then goes on to the path.
// - Paths of the app answer with the app page and the CSP the API sends; any other /v1 path is 404.

import { readFile } from 'node:fs/promises'
import { createServer, type IncomingMessage, type Server, type ServerResponse } from 'node:http'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const here = path.dirname(fileURLToPath(import.meta.url))
const BUILT = path.resolve(here, '../dist')
const FIXTURES = path.resolve(here, '../fixtures')
export const PORT = 4173

// The same policy the API sends with the app (src/household_vault/api/web.py).
const CSP =
  "default-src 'self'; img-src 'self' blob:; style-src 'self'; script-src 'self'; " +
  "connect-src 'self'; font-src 'self'; frame-ancestors 'none'; base-uri 'none'; " +
  "form-action 'self'"

const TYPES: Record<string, string> = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.json': 'application/json',
  '.png': 'image/png',
}

type Scenario = 'waiting' | 'one' | 'group' | 'empty' | 'down' | 'modeloff'
const SCENARIOS: Scenario[] = ['waiting', 'one', 'group', 'empty', 'down', 'modeloff']
const DOCS = ['doc-photo', 'doc-pdf']

function send(
  response: ServerResponse,
  status: number,
  type: string,
  body: string | Buffer,
  headers: Record<string, string> = {},
): void {
  response.writeHead(status, { 'Content-Type': type, 'Cache-Control': 'no-store', ...headers })
  response.end(body)
}

// Only a path on this site, never another host ("//host" is one).
function safeTarget(to: string | null): string {
  return to !== null && /^\/(?!\/)/.test(to) ? to : '/'
}

export async function serve(options: { port?: number; dist?: string } = {}): Promise<Server> {
  const DIST = options.dist ?? BUILT
  const lists: Record<string, string> = {
    waiting: await readFile(path.join(FIXTURES, 'needs-a-look.json'), 'utf8'),
    one: await readFile(path.join(FIXTURES, 'needs-a-look-one.json'), 'utf8'),
    group: await readFile(path.join(FIXTURES, 'needs-a-look-group.json'), 'utf8'),
    empty: '[]',
  }
  const health = await readFile(path.join(FIXTURES, 'healthz.json'), 'utf8')
  const refusal = JSON.stringify({ detail: 'Something went wrong. Nothing was changed.' })
  let scenario: Scenario = 'waiting'

  const recorded = async (name: string): Promise<string> =>
    readFile(path.join(FIXTURES, name), 'utf8')
  const notFile = JSON.stringify({ detail: 'That file is not available.' })

  type Body = { prompt?: string; full?: boolean; change?: unknown; query?: { areas?: string[] } }

  async function readBody(request: IncomingMessage): Promise<Body> {
    const chunks: Buffer[] = []
    for await (const chunk of request) chunks.push(chunk as Buffer)
    try {
      return JSON.parse(Buffer.concat(chunks).toString('utf8')) as Body
    } catch {
      return {}
    }
  }

  async function answer(
    url: string,
    response: ServerResponse,
    request: IncomingMessage,
  ): Promise<void> {
    const { pathname, searchParams } = new URL(url, `http://127.0.0.1:${PORT}`)
    const picked = /^\/__scenario\/(\w+)$/.exec(pathname)?.[1] as Scenario | undefined
    if (picked !== undefined && SCENARIOS.includes(picked)) {
      scenario = picked
      return send(response, 302, 'text/plain', '', { Location: safeTarget(searchParams.get('to')) })
    }
    if (pathname === '/healthz') return send(response, 200, TYPES['.json']!, health)
    if (pathname === '/v1/needs-a-look') {
      if (scenario === 'down') return send(response, 500, TYPES['.json']!, refusal)
      return send(response, 200, TYPES['.json']!, lists[scenario] ?? lists.waiting!)
    }
    if (pathname === '/v1/activity') {
      const older = searchParams.has('before')
      return send(response, 200, TYPES['.json']!, older ? '[]' : await recorded('activity.json'))
    }
    if (pathname === '/v1/inbox/progress')
      return send(response, 200, TYPES['.json']!, await recorded('progress.json'))
    if (pathname === '/v1/secrets/status')
      return send(response, 200, TYPES['.json']!, await recorded('secrets-status-none.json'))
    if (/^\/v1\/items\/\d+\/pages\/0\.png$/.test(pathname))
      return send(
        response,
        200,
        TYPES['.png']!,
        await readFile(path.join(FIXTURES, 'item-page-0.png')),
      )
    if (pathname === '/v1/people')
      return send(response, 200, TYPES['.json']!, await recorded('people.json'))
    if (pathname === '/v1/search/list' && request.method === 'POST') {
      const asked = await readBody(request)
      const areas = asked.query?.areas ?? []
      const file =
        asked.change !== undefined
          ? 'list-changed.json'
          : areas.includes('rent')
            ? 'list-area-empty.json'
            : areas.length > 0
              ? 'list-area.json'
              : 'search-list.json'
      return send(response, 200, TYPES['.json']!, await recorded(file))
    }
    if (pathname === '/v1/search' && request.method === 'POST') {
      const asked = await readBody(request)
      const prompt = (asked.prompt ?? '').toLowerCase()
      const file = prompt.includes('anil')
        ? 'search-no-answer.json'
        : asked.full === true && prompt.includes('expire')
          ? prompt.includes('diwali')
            ? 'search-list-unread.json'
            : 'search-list.json'
          : scenario === 'modeloff'
            ? 'search-model-off.json'
            : asked.full === true
              ? 'search-answer.json'
              : 'search-quick.json'
      return send(response, 200, TYPES['.json']!, await recorded(file))
    }
    const doc = /^\/v1\/documents\/([\w-]+)(?:\/(.*))?$/.exec(pathname)
    if (doc !== null) {
      const [, id = '', rest = ''] = doc
      if (!DOCS.includes(id)) return send(response, 404, TYPES['.json']!, notFile)
      if (rest === '') return send(response, 200, TYPES['.json']!, await recorded(`${id}.json`))
      if (rest === 'reveal') {
        const detail =
          'Show in folder works on the Mac itself, so the Drive path was copied instead.'
        return send(response, 409, TYPES['.json']!, JSON.stringify({ detail }))
      }
      const page = /^pages\/(\d+)(\.png|\/lines)$/.exec(rest)
      const number = page?.[1]
      const kind = page?.[2]
      const name = kind === '.png' ? `${id}-page-${number}.png` : `${id}-lines-${number}.json`
      const found =
        page === null ? null : await readFile(path.join(FIXTURES, name)).catch(() => null)
      if (found === null) return send(response, 404, TYPES['.json']!, notFile)
      return send(response, 200, kind === '.png' ? TYPES['.png']! : TYPES['.json']!, found)
    }
    if (request.method === 'POST' && pathname.startsWith('/v1/')) {
      await readBody(request)
      if (pathname.endsWith('/unlock') && pathname.includes('needs-a-look')) {
        const detail = 'That password did not open the file.'
        return send(response, 409, TYPES['.json']!, JSON.stringify({ detail }))
      }
      const card = pathname === '/v1/cards'
      const reply = card ? { status: 'asked', item_id: 4 } : { id: 4, state: 'queued' }
      return send(response, 200, TYPES['.json']!, JSON.stringify(reply))
    }
    if (pathname.startsWith('/v1/'))
      return send(response, 404, TYPES['.json']!, '{"detail":"Not found."}')
    const file = path.resolve(DIST, `.${pathname}`)
    const inside = file.startsWith(`${DIST}${path.sep}`)
    const body = inside ? await readFile(file).catch(() => null) : null
    if (body !== null) {
      const type = TYPES[path.extname(file)] ?? 'application/octet-stream'
      return send(response, 200, type, body, { 'Content-Security-Policy': CSP })
    }
    if (path.extname(pathname) !== '') return send(response, 404, 'text/plain', 'not found')
    const page = await readFile(path.join(DIST, 'index.html'))
    send(response, 200, TYPES['.html']!, page, { 'Content-Security-Policy': CSP })
  }

  const server = createServer((request, response) => {
    answer(request.url ?? '/', response, request).catch((error: unknown) => {
      send(response, 500, 'text/plain', String(error))
    })
  })
  await new Promise<void>((resolve, reject) => {
    server.once('error', reject)
    server.listen(options.port ?? PORT, '127.0.0.1', resolve)
  })
  return server
}

// Run on its own, it serves until stopped, for running pa11y-ci by hand or looking at the app.
if (process.argv[1] === fileURLToPath(import.meta.url)) {
  await serve()
  console.log(`serving dist/ at http://127.0.0.1:${PORT}`)
}

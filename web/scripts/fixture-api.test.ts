import { mkdtemp, rm, writeFile } from 'node:fs/promises'
import type { Server } from 'node:http'
import type { AddressInfo } from 'node:net'
import { tmpdir } from 'node:os'
import path from 'node:path'

import { afterEach, describe, expect, test } from 'vitest'

import { serve } from './fixture-api.ts'

let server: Server | undefined
let dist: string | undefined

async function start(): Promise<string> {
  dist = await mkdtemp(path.join(tmpdir(), 'dist-'))
  await writeFile(path.join(dist, 'index.html'), '<!doctype html><title>Vault</title>')
  server = await serve({ port: 0, dist })
  return `http://127.0.0.1:${(server.address() as AddressInfo).port}`
}

afterEach(async () => {
  server?.close()
  server = undefined
  if (dist !== undefined) await rm(dist, { recursive: true, force: true })
})

describe('the fixture API', () => {
  test('answers the Inbox list with the recorded replies', async () => {
    const base = await start()
    const list = (await (await fetch(`${base}/v1/needs-a-look`)).json()) as { name: string }[]
    expect(list.length).toBeGreaterThan(0)
    expect(list[0]?.name).toMatch(/\.(pdf|jpg|png)$/)
  })

  test('a scenario empties the list or breaks it, then goes on to the page asked for', async () => {
    const base = await start()
    const moved = await fetch(`${base}/__scenario/empty?to=/inbox`, { redirect: 'manual' })
    expect(moved.status).toBe(302)
    expect(moved.headers.get('location')).toBe('/inbox')
    expect(await (await fetch(`${base}/v1/needs-a-look`)).json()).toEqual([])
    await fetch(`${base}/__scenario/down?to=/`, { redirect: 'manual' })
    const broken = await fetch(`${base}/v1/needs-a-look`)
    expect(broken.status).toBe(500)
    expect(((await broken.json()) as { detail: string }).detail).toMatch(/Nothing was changed/)
  })

  test('only a path on this site can be gone to', async () => {
    const base = await start()
    const moved = await fetch(`${base}/__scenario/empty?to=//elsewhere.example`, {
      redirect: 'manual',
    })
    expect(moved.headers.get('location')).toBe('/')
  })

  test('serves the app page with the CSP for its own paths and 404 for an API path', async () => {
    const base = await start()
    const page = await fetch(`${base}/area/tax`)
    expect(page.status).toBe(200)
    expect(page.headers.get('content-security-policy')).toContain("default-src 'self'")
    expect((await fetch(`${base}/v1/nothing`)).status).toBe(404)
  })

  test('answers the search routes with the recorded replies', async () => {
    const base = await start()
    const ask = async (prompt: string, full: boolean) =>
      (await (
        await fetch(`${base}/v1/search`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ prompt, full }),
        })
      ).json()) as {
        rows: unknown[]
        answer: { text: string } | null
        no_answer: unknown
        reading: string
      }
    expect((await ask('policy', false)).rows.length).toBeGreaterThan(0)
    expect((await ask('policy number', true)).answer?.text).toMatch(/^P\//)
    expect((await ask('anil policy', true)).no_answer).not.toBeNull()
    await fetch(`${base}/__scenario/modeloff?to=/`, { redirect: 'manual' })
    expect((await ask('policy', true)).reading).toBe('off')
    const people = (await (await fetch(`${base}/v1/people`)).json()) as { name: string }[]
    expect(people.length).toBeGreaterThan(0)
  })

  test('serves a document, its lines and its page image, and refuses an unknown one', async () => {
    const base = await start()
    const doc = (await (await fetch(`${base}/v1/documents/doc-photo`)).json()) as {
      page_count: number
    }
    expect(doc.page_count).toBe(1)
    const lines = (await (await fetch(`${base}/v1/documents/doc-pdf/pages/0/lines`)).json()) as {
      lines: unknown[]
    }
    expect(lines.lines.length).toBeGreaterThan(0)
    const png = await fetch(`${base}/v1/documents/doc-pdf/pages/0.png?width=900`)
    expect(png.headers.get('content-type')).toBe('image/png')
    expect((await fetch(`${base}/v1/documents/nope`)).status).toBe(404)
    expect((await fetch(`${base}/v1/documents/doc-pdf/pages/9.png`)).status).toBe(404)
    const reveal = await fetch(`${base}/v1/documents/doc-pdf/reveal`, { method: 'POST' })
    expect(reveal.status).toBe(409)
  })

  test('scenarios give one file, or several that ask the same thing', async () => {
    const base = await start()
    const count = async (): Promise<number> =>
      ((await (await fetch(`${base}/v1/needs-a-look`)).json()) as unknown[]).length
    await fetch(`${base}/__scenario/one?to=/inbox`, { redirect: 'manual' })
    expect(await count()).toBe(1)
    await fetch(`${base}/__scenario/group?to=/inbox`, { redirect: 'manual' })
    const group = (await (await fetch(`${base}/v1/needs-a-look`)).json()) as {
      question: { text: string }
    }[]
    expect(group.length).toBeGreaterThan(1)
    expect(new Set(group.map((g) => g.question.text)).size).toBe(1)
  })

  test('serves the activity, the batch, the secrets status and a waiting file page', async () => {
    const base = await start()
    const log = (await (await fetch(`${base}/v1/activity?limit=20`)).json()) as { id: number }[]
    expect(log.length).toBeGreaterThan(0)
    expect(await (await fetch(`${base}/v1/activity?limit=20&before=1`)).json()).toEqual([])
    const batch = (await (await fetch(`${base}/v1/inbox/progress`)).json()) as {
      total_in_batch: number
    }
    expect(batch.total_in_batch).toBeGreaterThan(0)
    const status = (await (await fetch(`${base}/v1/secrets/status`)).json()) as object
    expect(Object.keys(status).sort()).toEqual(['exists', 'unlocked'])
    const png = await fetch(`${base}/v1/items/4/pages/0.png?width=900`)
    expect(png.headers.get('content-type')).toBe('image/png')
  })

  test('answers what the Inbox posts, so the screen can be used without the vault', async () => {
    const base = await start()
    const post = (route: string) => fetch(`${base}${route}`, { method: 'POST', body: '{}' })
    expect((await post('/v1/needs-a-look/4/answer')).status).toBe(200)
    expect((await post('/v1/needs-a-look/answer-many')).status).toBe(200)
    expect((await post('/v1/needs-a-look/4/unlock')).status).toBe(409)
    expect((await post('/v1/secrets/create')).status).toBe(200)
    expect((await post('/v1/cards')).status).toBe(200)
  })

  test('the unsure scenario asks a question the app doubts', async () => {
    const base = await start()
    await fetch(`${base}/__scenario/unsure?to=/inbox`, { redirect: 'manual' })
    const list = (await (await fetch(`${base}/v1/needs-a-look`)).json()) as {
      reasons: string[]
    }[]
    expect(list).toHaveLength(1)
    expect(list[0]?.reasons).toEqual(['person_unsure'])
  })

  test('the filed scenario logs a fresh filing for the file on screen, with a document to undo', async () => {
    const base = await start()
    await fetch(`${base}/__scenario/filed?to=/inbox`, { redirect: 'manual' })
    const [item] = (await (await fetch(`${base}/v1/needs-a-look`)).json()) as { id: number }[]
    const log = (await (await fetch(`${base}/v1/activity?limit=50`)).json()) as {
      item_id: number
      step: string
      document_id: string | null
      time: string
      actions: string[]
    }[]
    const filed = log.find((entry) => entry.item_id === item?.id && entry.step === 'filed')
    expect(filed?.document_id).toBe('doc-pdf')
    expect(filed?.actions).toContain('undo')
    expect(Date.now() - Date.parse(filed?.time ?? '')).toBeLessThan(60_000)
  })

  test('the failed scenario logs a file the app could not read, with a retry', async () => {
    const base = await start()
    await fetch(`${base}/__scenario/failed?to=/inbox`, { redirect: 'manual' })
    const log = (await (await fetch(`${base}/v1/activity?limit=50`)).json()) as {
      step: string
      actions: string[]
    }[]
    expect(log.find((entry) => entry.step === 'error')?.actions).toEqual(['retry'])
  })
})

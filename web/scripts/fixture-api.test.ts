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
})

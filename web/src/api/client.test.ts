import { afterEach, describe, expect, test, vi } from 'vitest'

import { ApiError, api, superseding } from './client.ts'

function reply(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

// A fetch that never answers until its request is aborted, as a slow API would.
function slowFetch() {
  return vi.fn<(url: string, init?: RequestInit) => Promise<Response>>(
    (_url: string, init?: RequestInit) =>
      new Promise<Response>((_resolve, reject) => {
        init?.signal?.addEventListener('abort', () =>
          reject(new DOMException('aborted', 'AbortError')),
        )
      }),
  )
}

afterEach(() => {
  vi.unstubAllGlobals()
})

// The error a request ends in, as the ApiError it is.
async function failure(request: Promise<unknown>): Promise<ApiError> {
  try {
    await request
  } catch (error) {
    if (error instanceof ApiError) return error
    throw error
  }
  throw new Error('the request did not fail')
}

describe('api', () => {
  test('returns the parsed JSON of a good answer', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn<() => Promise<Response>>().mockResolvedValue(reply(200, [{ id: 3 }])),
    )
    expect(await api<{ id: number }[]>('/v1/needs-a-look')).toEqual([{ id: 3 }])
  })

  test('sends a JSON body with its header', async () => {
    const fetchMock = vi
      .fn<(url: string, init?: RequestInit) => Promise<Response>>()
      .mockResolvedValue(reply(200, {}))
    vi.stubGlobal('fetch', fetchMock)
    await api('/v1/search', { method: 'POST', body: JSON.stringify({ prompt: 'x' }) })
    const init = fetchMock.mock.calls[0]![1] as RequestInit
    expect(new Headers(init.headers).get('Content-Type')).toBe('application/json')
  })

  test('an error carries the detail sentence the API gave', async () => {
    vi.stubGlobal(
      'fetch',
      vi
        .fn<() => Promise<Response>>()
        .mockResolvedValue(reply(409, { detail: 'The file moved. Nothing was changed.' })),
    )
    const error = await failure(api('/v1/documents/1/undo', { method: 'POST' }))
    expect(error).toBeInstanceOf(ApiError)
    expect((error as ApiError).message).toBe('The file moved. Nothing was changed.')
    expect((error as ApiError).status).toBe(409)
  })

  test('a validation error list becomes one sentence, and a bare error a plain one', async () => {
    vi.stubGlobal(
      'fetch',
      vi
        .fn<() => Promise<Response>>()
        .mockResolvedValue(reply(422, { detail: [{ loc: ['body', 'prompt'], msg: 'too long' }] })),
    )
    const first = await failure(api('/v1/search'))
    expect(first.message).toBe('too long')
    vi.stubGlobal(
      'fetch',
      vi.fn<() => Promise<Response>>().mockResolvedValue(new Response('boom', { status: 500 })),
    )
    const second = await failure(api('/v1/search'))
    expect(second.message).toBe('Something went wrong. Nothing was changed.')
  })

  test('a network failure says the app cannot be reached', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn<() => Promise<Response>>().mockRejectedValue(new TypeError('Failed to fetch')),
    )
    const error = await failure(api('/healthz'))
    expect(error).toBeInstanceOf(ApiError)
    expect(error.message).toBe('The vault is not answering. Check that it is running.')
    expect(error.status).toBe(0)
  })

  test('an abort stays an abort, not an error to show', async () => {
    vi.stubGlobal('fetch', slowFetch())
    const controller = new AbortController()
    const pending = api('/v1/search', { signal: controller.signal })
    controller.abort()
    await expect(pending).rejects.toMatchObject({ name: 'AbortError' })
  })
})

describe('superseding', () => {
  test('aborts a superseded request and carries the API detail on an error', async () => {
    const fetchMock = slowFetch()
    vi.stubGlobal('fetch', fetchMock)
    const latest = superseding()
    const first = latest('/v1/search')
    const firstSignal = (fetchMock.mock.calls[0]![1] as RequestInit).signal as AbortSignal
    expect(firstSignal.aborted).toBe(false)

    vi.stubGlobal(
      'fetch',
      vi
        .fn<() => Promise<Response>>()
        .mockResolvedValue(reply(422, { detail: 'Prompts can be up to 300 characters.' })),
    )
    const second = failure(latest('/v1/search'))

    await expect(first).rejects.toMatchObject({ name: 'AbortError' })
    expect(firstSignal.aborted).toBe(true)
    expect((await second).message).toBe('Prompts can be up to 300 characters.')
  })

  test('a finished request is not aborted by the next one', async () => {
    const fetchMock = vi.fn<() => Promise<Response>>(() => Promise.resolve(reply(200, { ok: 1 })))
    vi.stubGlobal('fetch', fetchMock)
    const latest = superseding()
    expect(await latest('/a')).toEqual({ ok: 1 })
    expect(await latest('/b')).toEqual({ ok: 1 })
  })
})

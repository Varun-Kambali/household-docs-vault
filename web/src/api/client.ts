// One way to call the API. Every request goes to this page's own origin (the dev server proxies
// /v1 to the API), and a refusal comes back as an ApiError whose message is the sentence the API
// wrote, so a screen can show it as it is.

const FALLBACK = 'Something went wrong. Nothing was changed.'
const UNREACHABLE = 'The vault is not answering. Check that it is running.'

export class ApiError extends Error {
  readonly status: number

  constructor(message: string, status: number) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

type Detail = string | { msg?: unknown }[] | undefined

// The API's `detail` is a sentence, or (for a request it could not read) a list of problems.
function sentence(detail: Detail): string {
  if (typeof detail === 'string' && detail !== '') return detail
  if (Array.isArray(detail)) {
    const first = detail[0]?.msg
    if (typeof first === 'string' && first !== '') return first
  }
  return FALLBACK
}

function isAbort(error: unknown): boolean {
  return error instanceof DOMException && error.name === 'AbortError'
}

export function api<T>(path: string, init?: RequestInit & { signal?: AbortSignal }): Promise<T> {
  const headers = new Headers(init?.headers)
  if (init?.body !== undefined && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }
  return request<T>(path, { ...init, headers })
}

async function request<T>(path: string, init: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(path, init)
  } catch (error) {
    // A request that was aborted on purpose is not a failure to show.
    if (isAbort(error)) throw error
    throw new ApiError(UNREACHABLE, 0)
  }
  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as { detail?: Detail } | null
    throw new ApiError(sentence(body?.detail), response.status)
  }
  return (await response.json()) as T
}

// A caller for one box that is typed into: each call aborts the one before it, so a slow answer
// to an old prompt can never arrive after, and replace, the answer to the new one.
export function superseding(): <T>(path: string, init?: RequestInit) => Promise<T> {
  let current: AbortController | undefined
  return <T>(path: string, init?: RequestInit) => {
    current?.abort()
    const controller = new AbortController()
    current = controller
    return api<T>(path, { ...init, signal: controller.signal })
  }
}

export { isAbort }

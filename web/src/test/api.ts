// A stand-in for the API in a test: a handler answers by method and path, every call is kept, and
// a request is rejected with an abort when its signal fires, as a real fetch would be.
import { vi } from 'vitest'

import type {
  AnswerOut,
  DocumentOut,
  ListOut,
  NoAnswerOut,
  QueryOut,
  RowOut,
  SearchOut,
  SentenceOut,
} from '../api/types.ts'

export type Call = { method: string; path: string; body: unknown; signal: AbortSignal | null }
export type Reply = { status?: number; body?: unknown } | 'hang'

export function stubApi(handler: (call: Call) => Reply | undefined) {
  const calls: Call[] = []
  const fetchMock = vi.fn<(input: RequestInfo | URL, init?: RequestInit) => Promise<Response>>(
    (input, init) => {
      const url = new URL(String(input), 'http://localhost')
      const call: Call = {
        method: init?.method ?? 'GET',
        path: url.pathname + url.search,
        body: typeof init?.body === 'string' ? JSON.parse(init.body) : undefined,
        signal: init?.signal ?? null,
      }
      calls.push(call)
      const reply = handler(call) ?? { status: 404, body: { detail: 'Not found.' } }
      if (reply === 'hang') {
        return new Promise<Response>((_resolve, reject) => {
          call.signal?.addEventListener('abort', () =>
            reject(new DOMException('aborted', 'AbortError')),
          )
        })
      }
      const status = reply.status ?? 200
      return Promise.resolve(
        status === 204
          ? new Response(null, { status })
          : new Response(JSON.stringify(reply.body ?? {}), {
              status,
              headers: { 'Content-Type': 'application/json' },
            }),
      )
    },
  )
  vi.stubGlobal('fetch', fetchMock)
  return { calls, fetchMock }
}

export const PEOPLE = [
  { id: 'p1', name: 'Ravi Kumar Rao' },
  { id: 'p2', name: 'Kavita Rao' },
]

export function row(over: Partial<RowOut> = {}): RowOut {
  return {
    document_id: 'doc-a',
    doc_type: 'health_policy',
    owner: 'p2',
    people: ['p2'],
    area: 'insurance',
    rel_path: 'Kavita Rao/Insurance/2026-09-20 Health policy - Care Health.pdf',
    drive_path:
      'My Drive/Family Vault/Kavita Rao/Insurance/2026-09-20 Health policy - Care Health.pdf',
    doc_date: '2026-09-20',
    key_fields: { insurer: 'Care Health', policy_number: 'P/21/2138/5675525' },
    field_kinds: { insurer: 'text', policy_number: 'identifier' },
    date: '2026-09-20',
    score: 0.03,
    lines: [{ page: 0, idx: 3, bbox: [0.07, 0.15, 0.17, 0.16] }],
    ...over,
  }
}

export function answer(over: Partial<AnswerOut> = {}): AnswerOut {
  return {
    text: 'P/21/2138/5675525',
    field: 'policy_number',
    value: 'P/21/2138/5675525',
    document_id: 'doc-a',
    page: 0,
    lines: [{ page: 0, idx: 3, bbox: [0.32, 0.15, 0.47, 0.165] }],
    masked: false,
    ...over,
  }
}

export function search(over: Partial<SearchOut> = {}): SearchOut {
  return { rows: [row()], reading: 'on', vectors: 'on', ...over }
}

export function noAnswer(over: Partial<NoAnswerOut> = {}): NoAnswerOut {
  return { reason: 'weak_match', closest: [row().rel_path], ...over }
}

export const LINES = {
  page: 0,
  lines: [
    { idx: 0, text: 'Care Health Insurance Limited', bbox: [0.07, 0.03, 0.48, 0.05] },
    { idx: 3, text: 'Policy Number', bbox: [0.07, 0.15, 0.17, 0.16] },
    { idx: 4, text: 'P/21/2138/5675525', bbox: [0.32, 0.15, 0.47, 0.165] },
  ],
}

export function document(over: Partial<DocumentOut> = {}): DocumentOut {
  return {
    id: 'doc-a',
    item_id: 1,
    doc_type: 'health_policy',
    owner: 'p2',
    area: 'insurance',
    rel_path: row().rel_path,
    doc_date: '2026-09-20',
    date_source: 'document',
    description: 'Health policy - Care Health',
    fields: { insurer: 'Care Health', policy_number: 'P/21/2138/5675525' },
    issues: {},
    created_at: '2026-09-20T10:00:00+05:30',
    drive_path: row().drive_path,
    people: ['p2'],
    field_kinds: { insurer: 'text', policy_number: 'identifier' },
    page_count: 2,
    ...over,
  }
}

export function choice(value: unknown, label: string) {
  return { value, label } as { value: never; label: string }
}

// The sentence the API writes for a list of expiring health policies, with every menu it offers.
export function sentence(over: Partial<SentenceOut> = {}): SentenceOut {
  return {
    text: 'Showing Health policies for everyone that expire any time',
    parts: [
      {
        slot: 'what',
        text: 'Health policies',
        value: null,
        options: [
          choice('all', 'all documents'),
          choice('area:insurance', 'Insurance'),
          choice('type:health_policy', 'Health policy'),
          choice('type:life_policy', 'Life policy'),
        ],
      },
      {
        slot: 'who',
        text: 'everyone',
        value: [],
        options: [
          choice([], 'everyone'),
          choice('p1', 'Ravi Kumar Rao'),
          choice('p2', 'Kavita Rao'),
        ],
      },
      {
        slot: 'verb',
        text: 'expire',
        value: 'expiry',
        options: [
          choice('expiry', 'expire'),
          choice('renewal', 'renew'),
          choice('document', 'are dated'),
        ],
      },
      {
        slot: 'when',
        text: 'any time',
        value: null,
        options: [
          choice('any', 'any time'),
          choice('next_30', 'next 30 days'),
          choice('before:2027-01-01', 'before 1 Jan 2027'),
          choice('custom', 'a custom range'),
        ],
      },
    ],
    ...over,
  }
}

export function listQuery(over: Partial<QueryOut> = {}): QueryOut {
  return {
    intent: 'list',
    people: [],
    types: ['health_policy'],
    areas: [],
    field: null,
    role: 'expiry',
    range: null,
    place: null,
    words: '',
    unread: [],
    ...over,
  }
}

export function listOut(over: Partial<ListOut> = {}): ListOut {
  return {
    rows: [row({ document_id: 'doc-a', date: '2026-09-20' })],
    sentence: sentence(),
    query: listQuery(),
    ...over,
  }
}

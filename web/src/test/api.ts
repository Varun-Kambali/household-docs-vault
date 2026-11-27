// A stand-in for the API in a test: a handler answers by method and path, every call is kept, and
// a request is rejected with an abort when its signal fires, as a real fetch would be.
import { vi } from 'vitest'

import type {
  ActivityOut,
  AnswerOut,
  DocumentOut,
  ListOut,
  NeedsALookOut,
  NoAnswerOut,
  ProgressOut,
  QueryOut,
  RowOut,
  SearchOut,
  SentenceOut,
} from '../api/types.ts'

export type Call = { method: string; path: string; body: unknown; signal: AbortSignal | null }
export type Reply = { status?: number; body?: unknown } | 'hang' | Promise<Reply>

// A reply that is a promise is held until the test resolves it, so a test can move on while a
// request is still on its way.
function settle(reply: Reply): Promise<Response> {
  if (reply instanceof Promise) return reply.then(settle)
  if (reply === 'hang') return new Promise<Response>(() => undefined)
  const status = reply.status ?? 200
  return Promise.resolve(
    status === 204
      ? new Response(null, { status })
      : new Response(JSON.stringify(reply.body ?? {}), {
          status,
          headers: { 'Content-Type': 'application/json' },
        }),
  )
}

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
      return settle(reply)
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

// The Inbox: a file waiting on "Whose is it?", with the people as the API sends them.
export function waitingItem(over: Partial<NeedsALookOut> = {}): NeedsALookOut {
  return {
    id: 7,
    name: 'prescription-1.pdf',
    file: 'Needs a look/prescription-1.pdf',
    reasons: ['person_unknown'],
    question: {
      reason: 'person_unknown',
      text: 'Prescription with no name I know on it. Whose is it?',
      answer_kind: 'person',
      options: [
        { value: 'p1', label: 'Ravi Kumar Rao' },
        { value: 'p2', label: 'Kavita Rao' },
        { value: 'home', label: 'Home' },
      ],
      field: null,
    },
    since: '2026-11-26T08:53:07+05:30',
    ...over,
  }
}

export function lockedItem(over: Partial<NeedsALookOut> = {}): NeedsALookOut {
  return waitingItem({
    id: 3,
    name: 'policy-locked.pdf',
    file: 'Needs a look/policy-locked.pdf',
    reasons: ['locked'],
    question: {
      reason: 'locked',
      text: 'This PDF is locked. Unlock it with its password to read it.',
      answer_kind: 'unlock',
      options: [{ value: 'unlock', label: 'Unlock' }],
      field: null,
    },
    ...over,
  })
}

export function activityEntry(over: Partial<ActivityOut> = {}): ActivityOut {
  return {
    id: 10,
    time: '2026-11-26T08:53:07+05:30',
    item_id: 7,
    step: 'filed',
    outcome: 'filed',
    file: 'Kavita Rao/Health/2026-09-20 Prescription.pdf',
    detail: 'Filed as Prescription',
    actions: ['open', 'undo'],
    document_id: 'doc-a',
    ...over,
  }
}

export function idle(over: Partial<ProgressOut> = {}): ProgressOut {
  return {
    waiting: 0,
    current: null,
    step: null,
    total_in_batch: 0,
    done_in_batch: 0,
    asked_in_batch: 0,
    batch_started_at: null,
    ...over,
  }
}

// A card-like number for a test, built here from its prefix with a Luhn check digit, so no number
// is written into a fixture. It is only ever put into a prompt to see it masked.
export function testCard(prefix = '411111', length = 16): string {
  const body = prefix.padEnd(length - 1, '1')
  let sum = 0
  for (let i = 0; i < body.length; i += 1) {
    let n = Number(body[body.length - 1 - i])
    if (i % 2 === 0) {
      n *= 2
      if (n > 9) n -= 9
    }
    sum += n
  }
  return body + String((10 - (sum % 10)) % 10)
}

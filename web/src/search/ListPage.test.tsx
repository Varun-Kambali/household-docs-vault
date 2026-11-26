import { act, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'

import { App } from '../app/App.tsx'
import { navigate } from '../app/location.ts'
import {
  PEOPLE,
  listOut,
  listQuery,
  row,
  search,
  sentence,
  stubApi,
  type Call,
  type Reply,
} from '../test/api.ts'

function open(path: string): void {
  window.history.replaceState(null, '', path)
}

type Replies = { full?: Reply; list?: (call: Call) => Reply | undefined }

function api(replies: Replies = {}) {
  return stubApi((call: Call): Reply | undefined => {
    if (call.path === '/v1/needs-a-look') return { body: [] }
    if (call.path === '/v1/people') return { body: PEOPLE }
    if (call.path === '/v1/search') {
      const full = (call.body as { full: boolean }).full
      if (!full) return { body: search() }
      return (
        replies.full ?? {
          body: search({ ...listOut(), reading: 'on', vectors: 'on' }),
        }
      )
    }
    if (call.path === '/v1/search/list') return replies.list?.(call) ?? { body: listOut() }
    return undefined
  })
}

const lists = (calls: Call[]) => calls.filter((c) => c.path === '/v1/search/list')
const searches = (calls: Call[]) => calls.filter((c) => c.path === '/v1/search')

async function wait(ms: number): Promise<void> {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms)
  })
}

beforeEach(() => {
  vi.useFakeTimers()
  open('/')
})
afterEach(() => {
  vi.useRealTimers()
  open('/')
})

const box = () => screen.getByRole('searchbox', { name: 'Ask about your documents' })
const menu = (name: string) => screen.getByRole('combobox', { name })
const rowsShown = () =>
  within(screen.getByRole('list', { name: 'Documents' }))
    .getAllByRole('listitem')
    .map((li) => li.textContent)

async function askForList(): Promise<void> {
  render(<App />)
  fireEvent.change(box(), { target: { value: 'health policies that expire' } })
  await wait(600)
}

// The user picks a menu entry (one change event), and the reply to it arrives.
function choose(name: string, label: string): void {
  const option = within(menu(name)).getByRole('option', { name: label }) as HTMLOptionElement
  fireEvent.change(menu(name), { target: { value: option.value } })
}

async function pick(name: string, label: string): Promise<void> {
  choose(name, label)
  await wait(0)
}

describe('a list from a prompt', () => {
  test('shows the sentence and the rows, not the quick finder or an answer', async () => {
    api()
    await askForList()
    expect(menu('Kind of document')).toHaveDisplayValue('Health policy')
    expect(screen.getByText('1 document')).toBeInTheDocument()
    expect(rowsShown()).toHaveLength(1)
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
  })

  test('changing who posts /v1/search/list and never /v1/search', async () => {
    const { calls } = api({
      list: () => ({ body: listOut({ query: listQuery({ people: ['p2'] }) }) }),
    })
    await askForList()
    const before = searches(calls).length
    await pick('Person', 'Kavita Rao')
    expect(lists(calls)).toHaveLength(1)
    expect(lists(calls)[0]?.method).toBe('POST')
    expect(lists(calls)[0]?.body).toMatchObject({
      query: { intent: 'list', types: ['health_policy'], role: 'expiry', people: [] },
      change: { slot: 'who', value: 'p2' },
    })
    expect(searches(calls)).toHaveLength(before)
  })

  test('the change replaces the rows and the sentence', async () => {
    api({
      list: () => ({
        body: listOut({
          rows: [row({ document_id: 'doc-new', rel_path: 'Kavita Rao/Insurance/New policy.pdf' })],
          query: listQuery({ people: ['p2'], types: ['life_policy'] }),
          sentence: sentence({ text: 'x' }),
        }),
      }),
    })
    await askForList()
    await pick('Person', 'Kavita Rao')
    expect(rowsShown()).toHaveLength(1)
    expect(rowsShown()[0]).toContain('New policy')
    expect(menu('Person')).toHaveDisplayValue('Kavita Rao')
    expect(menu('Kind of document')).toHaveDisplayValue('Life policy')
  })

  test('the address then holds the query, and the prompt is gone from it', async () => {
    api({ list: () => ({ body: listOut({ query: listQuery({ people: ['p2'] }) }) }) })
    await askForList()
    await pick('Person', 'Kavita Rao')
    const params = new URLSearchParams(window.location.search)
    expect(window.location.pathname).toBe('/')
    expect(params.get('q')).toBeNull()
    expect(params.get('people')).toBe('p2')
    expect(params.get('types')).toBe('health_policy')
    expect(params.get('role')).toBe('expiry')
  })

  test('keeps the old rows and says so while a change is on its way', async () => {
    stubApi((call) => {
      if (call.path === '/v1/needs-a-look') return { body: [] }
      if (call.path === '/v1/people') return { body: PEOPLE }
      if (call.path === '/v1/search')
        return { body: search({ ...listOut(), reading: 'on', vectors: 'on' }) }
      if (call.path === '/v1/search/list') return 'hang'
      return undefined
    })
    await askForList()
    await pick('Person', 'Kavita Rao')
    expect(screen.getByText('Updating the list')).toBeInTheDocument()
    expect(rowsShown()).toHaveLength(1)
  })

  test('a change that fails says so and leaves the list as it was', async () => {
    api({
      list: () => ({
        status: 422,
        body: { detail: 'That change is not one the sentence offers.' },
      }),
    })
    await askForList()
    await pick('Person', 'Kavita Rao')
    expect(screen.getByRole('alert')).toHaveTextContent(
      'That change is not one the sentence offers.',
    )
    expect(rowsShown()).toHaveLength(1)
  })

  test('a part the server could not read is shown beside the sentence', async () => {
    api({
      full: {
        body: search({ ...listOut({ query: listQuery({ unread: ['before Diwali'] }) }) }),
      },
    })
    await askForList()
    expect(screen.getByText("Couldn't read: before Diwali")).toBeInTheDocument()
  })

  test('a custom range sends both dates', async () => {
    const { calls } = api()
    await askForList()
    await pick('When', 'a custom range')
    fireEvent.change(screen.getByLabelText('From'), { target: { value: '2026-12-01' } })
    await wait(0)
    fireEvent.change(screen.getByLabelText('To'), { target: { value: '2027-01-31' } })
    await wait(0)
    expect(lists(calls).at(-1)?.body).toMatchObject({
      change: { slot: 'when', value: { start: '2026-12-01', end: '2027-01-31' } },
    })
  })

  test('two quick changes are sent one after the other, the second on the first', async () => {
    const { calls } = api({
      list: (call) => {
        const change = (call.body as { change: { slot: string; value: unknown } }).change
        return {
          body: listOut({
            query: listQuery(change.slot === 'who' ? { people: ['p2'] } : { role: 'renewal' }),
          }),
        }
      },
    })
    await askForList()
    // both picked before the first answer has come back
    choose('Person', 'Kavita Rao')
    choose('Which date', 'renew')
    await wait(0)
    expect(lists(calls)).toHaveLength(2)
    expect(lists(calls)[1]?.body).toMatchObject({ query: { people: ['p2'] } })
  })

  test('typing a new prompt leaves the list', async () => {
    api()
    await askForList()
    fireEvent.change(box(), { target: { value: 'tax' } })
    await wait(150)
    expect(screen.queryByRole('list', { name: 'Documents' })).not.toBeInTheDocument()
  })
})

describe('a list from the address', () => {
  test('reloading a changed list posts /v1/search/list with that query and never /v1/search', async () => {
    const { calls } = api()
    open('/?people=p2&types=health_policy&role=expiry&from=2026-12-01&to=2027-01-31&place=Pune')
    render(<App />)
    await wait(1000)
    expect(searches(calls)).toHaveLength(0)
    expect(lists(calls)).toHaveLength(1)
    expect(lists(calls)[0]?.body).toEqual({
      query: {
        intent: 'list',
        people: ['p2'],
        types: ['health_policy'],
        areas: [],
        field: null,
        role: 'expiry',
        range: { start: '2026-12-01', end: '2027-01-31' },
        place: 'Pune',
        words: '',
        unread: [],
      },
    })
    expect(screen.getByText('1 document')).toBeInTheDocument()
  })

  test('shows a loading note, then an error in words when the list cannot be read', async () => {
    api({
      list: () => ({ status: 500, body: { detail: 'Something went wrong. Nothing was changed.' } }),
    })
    open('/?list=1')
    render(<App />)
    expect(screen.getByText(/Loading/)).toBeInTheDocument()
    await wait(0)
    expect(screen.getByRole('alert')).toHaveTextContent('Something went wrong.')
  })

  test('a list with nothing in it says so', async () => {
    api({ list: () => ({ body: listOut({ rows: [] }) }) })
    open('/?role=due')
    render(<App />)
    await wait(0)
    expect(screen.getByText('No documents match this.')).toBeInTheDocument()
    expect(menu('Person')).toBeInTheDocument()
  })

  test('changing a part of a linked list does not ask the model either', async () => {
    const { calls } = api({
      list: (call) => ({
        body: listOut({
          query: listQuery(
            (call.body as { change?: unknown }).change === undefined ? {} : { people: ['p1'] },
          ),
        }),
      }),
    })
    open('/?types=health_policy&role=expiry')
    render(<App />)
    await wait(0)
    await pick('Person', 'Ravi Kumar Rao')
    expect(searches(calls)).toHaveLength(0)
    expect(lists(calls)).toHaveLength(2)
    expect(new URLSearchParams(window.location.search).get('people')).toBe('p1')
    // the new address is the list on screen: nothing is fetched again for it
    await wait(1000)
    expect(lists(calls)).toHaveLength(2)
  })
})

describe('an area page', () => {
  test('lists the area by a structured query, with no prompt and no model call', async () => {
    const { calls } = api({
      list: () => ({
        body: listOut({ query: listQuery({ types: [], areas: ['insurance'], role: null }) }),
      }),
    })
    open('/area/insurance')
    render(<App />)
    await wait(1000)
    expect(screen.getByRole('heading', { level: 1, name: 'Insurance' })).toBeInTheDocument()
    expect(searches(calls)).toHaveLength(0)
    expect(lists(calls)).toHaveLength(1)
    expect(lists(calls)[0]?.body).toEqual({
      query: {
        intent: 'list',
        people: [],
        types: [],
        areas: ['insurance'],
        field: null,
        role: null,
        range: null,
        place: null,
        words: '',
        unread: [],
      },
    })
    expect(rowsShown()).toHaveLength(1)
    expect(screen.queryByRole('searchbox')).not.toBeInTheDocument()
  })

  test('an empty area says nothing is filed under it', async () => {
    api({
      list: () => ({
        body: listOut({ rows: [], query: listQuery({ types: [], areas: ['rent'] }) }),
      }),
    })
    open('/area/rent')
    render(<App />)
    await wait(0)
    expect(screen.getByText('Nothing filed under Rent yet.')).toBeInTheDocument()
  })

  test('can be narrowed from the sentence, and keeps its path with the params', async () => {
    const { calls } = api({
      list: (call) => ({
        body: listOut({
          query: listQuery({
            types: [],
            areas: ['insurance'],
            role: null,
            people: (call.body as { change?: unknown }).change === undefined ? [] : ['p2'],
          }),
        }),
      }),
    })
    open('/area/insurance')
    render(<App />)
    await wait(0)
    await pick('Person', 'Kavita Rao')
    expect(window.location.pathname).toBe('/area/insurance')
    expect(window.location.search).toBe('?people=p2&areas=insurance')
    expect(lists(calls)).toHaveLength(2)
    expect(searches(calls)).toHaveLength(0)
  })

  test('coming back to the area with nothing narrowed uses the bare path', async () => {
    api({
      list: () => ({
        body: listOut({ query: listQuery({ types: [], areas: ['insurance'], role: null }) }),
      }),
    })
    open('/area/insurance')
    render(<App />)
    await wait(0)
    await pick('Person', 'everyone')
    expect(window.location.search).toBe('')
  })

  test('an area page reloaded with params lists from them', async () => {
    const { calls } = api()
    open('/area/insurance?people=p2&areas=insurance')
    render(<App />)
    await wait(0)
    expect(lists(calls)[0]?.body).toMatchObject({ query: { people: ['p2'], areas: ['insurance'] } })
  })
})

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((done) => {
    resolve = done
  })
  return { promise, resolve }
}

const isChange = (call: Call) => (call.body as { change?: unknown }).change !== undefined

describe('changes still on their way', () => {
  const late = () =>
    listOut({
      rows: [row({ document_id: 'late', rel_path: 'Late/Old list.pdf' })],
      query: listQuery({ people: ['p2'] }),
    })

  test('a reply that comes after a new prompt is dropped, and the address stays on the prompt', async () => {
    const held = deferred<Reply>()
    api({ list: (call) => (isChange(call) ? held.promise : undefined) })
    await askForList()
    choose('Person', 'Kavita Rao')
    await wait(0)
    fireEvent.change(box(), { target: { value: 'tax' } })
    await wait(150)
    held.resolve({ body: late() })
    await wait(0)
    expect(window.location.search).toBe('?q=tax')
    expect(screen.queryByText(/Old list/)).not.toBeInTheDocument()
    expect(screen.queryByRole('list', { name: 'Documents' })).not.toBeInTheDocument()
  })

  test('a reply that comes after moving to another list is dropped', async () => {
    const held = deferred<Reply>()
    api({ list: (call) => (isChange(call) ? held.promise : undefined) })
    await askForList()
    choose('Person', 'Kavita Rao')
    await wait(0)
    act(() => navigate('/area/rent'))
    await wait(0)
    held.resolve({ body: late() })
    await wait(0)
    expect(window.location.pathname).toBe('/area/rent')
    expect(window.location.search).toBe('')
    expect(screen.queryByText(/Old list/)).not.toBeInTheDocument()
  })

  test('picks on the same part collapse to the last one, so the queue stays small', async () => {
    const first = deferred<Reply>()
    let posted = 0
    const { calls } = api({
      list: (call) => (isChange(call) && posted++ === 0 ? first.promise : undefined),
    })
    await askForList()
    for (let i = 0; i < 10; i += 1) {
      choose('Person', i % 2 === 0 ? 'Kavita Rao' : 'Ravi Kumar Rao')
      choose('Which date', i % 2 === 0 ? 'renew' : 'are dated')
    }
    choose('Person', 'everyone')
    await wait(0)
    first.resolve({ body: listOut() })
    await wait(0)
    await wait(0)
    await wait(0)
    const changes = lists(calls)
      .map((c) => (c.body as { change?: { slot: string; value: unknown } }).change)
      .filter((c) => c !== undefined)
    // the first pick was already on its way; behind it, one change per part
    expect(changes).toEqual([
      { slot: 'who', value: 'p2' },
      { slot: 'verb', value: 'document' },
      { slot: 'who', value: [] },
    ])
  })
})

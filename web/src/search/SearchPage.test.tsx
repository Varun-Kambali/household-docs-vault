import { act, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'

import { App } from '../app/App.tsx'
import {
  LINES,
  PEOPLE,
  answer,
  noAnswer,
  row,
  search,
  stubApi,
  type Call,
  type Reply,
} from '../test/api.ts'

function open(path: string): void {
  window.history.replaceState(null, '', path)
}

type Searches = { quick?: Reply; full?: Reply; reveal?: Reply }

function api(replies: Searches = {}) {
  return stubApi((call: Call): Reply | undefined => {
    if (call.path === '/v1/needs-a-look') return { body: [] }
    if (call.path === '/v1/people') return { body: PEOPLE }
    if (call.path.endsWith('/lines')) return { body: LINES }
    if (call.path.endsWith('.png')) return { status: 404 }
    if (call.path === '/v1/search') {
      const full = (call.body as { full: boolean }).full
      return (
        (full ? replies.full : replies.quick) ?? {
          body: search(full ? { answer: answer() } : {}),
        }
      )
    }
    if (call.path.endsWith('/reveal')) return replies.reveal ?? { status: 204 }
    return undefined
  })
}

const searches = (calls: Call[], full?: boolean) =>
  calls.filter(
    (c) =>
      c.path === '/v1/search' &&
      (full === undefined || (c.body as { full: boolean }).full === full),
  )

async function wait(ms: number): Promise<void> {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms)
  })
}

beforeEach(() => {
  vi.useFakeTimers()
  const written: string[] = []
  vi.stubGlobal('navigator', {
    ...window.navigator,
    clipboard: {
      writeText: (text: string) => {
        written.push(text)
        return Promise.resolve()
      },
      readText: () => Promise.resolve(written.at(-1) ?? ''),
    },
  })
  open('/')
})
afterEach(() => {
  vi.useRealTimers()
  open('/')
})

function start(): void {
  render(<App />)
}

// Typing is a change of the box's value, as the browser makes it; the clock is the test's.
function setPrompt(text: string): void {
  fireEvent.change(box(), { target: { value: text } })
}

function press(key: string, modifiers: { metaKey?: boolean; ctrlKey?: boolean } = {}): void {
  fireEvent.keyDown(box(), { key, ...modifiers })
}

const box = () => screen.getByRole('searchbox', { name: 'Ask about your documents' })

describe('the search screen', () => {
  test('typing waits 150 ms, aborts the stale request and shows rows', async () => {
    const { calls } = api({ quick: 'hang' })
    start()
    setPrompt('pol')
    await wait(149)
    expect(searches(calls)).toHaveLength(0)
    await wait(1)
    expect(searches(calls)).toHaveLength(1)
    expect(searches(calls)[0]?.body).toEqual({ prompt: 'pol', full: false })
    // another key: the request that has not answered is aborted, and the new one asks again
    setPrompt('poli')
    expect(searches(calls)[0]?.signal?.aborted).toBe(true)
    await wait(150)
    expect(searches(calls, false)).toHaveLength(2)
    expect(searches(calls, false)[1]?.body).toEqual({ prompt: 'poli', full: false })
  })

  test('shows the rows the quick search found, one line each', async () => {
    api({
      quick: {
        body: search({
          rows: [row(), row({ document_id: 'doc-b', doc_type: 'tax_invoice', people: ['p1'] })],
        }),
      },
    })
    start()
    setPrompt('care')
    await wait(150)
    const list = screen.getByRole('listbox', { name: 'Matching files' })
    const options = within(list).getAllByRole('option')
    expect(options).toHaveLength(2)
    expect(options[0]).toHaveTextContent('Health policy')
    expect(options[0]).toHaveTextContent('Kavita Rao')
    expect(options[0]).toHaveTextContent('P/21/2138/5675525')
    expect(options[0]).toHaveTextContent('Kavita Rao/Insurance/2026-09-20 Health policy')
    expect(options[1]).toHaveTextContent('Invoice')
    expect(options[1]).toHaveTextContent('Ravi Kumar Rao')
    // the matched word is bold, not coloured
    expect(within(options[0]!).getAllByText('Care', { selector: 'strong' })[0]).toBeInTheDocument()
  })

  test('says so when nothing matches, and when the search fails', async () => {
    api({ quick: { body: search({ rows: [] }) } })
    start()
    setPrompt('zzz')
    await wait(150)
    expect(screen.getByText('No file matches that.')).toBeInTheDocument()
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
  })

  test('a failed search shows the sentence the API gave', async () => {
    api({ quick: { status: 500, body: { detail: 'Search is not working right now.' } } })
    start()
    setPrompt('zzz')
    await wait(150)
    expect(screen.getByRole('alert')).toHaveTextContent('Search is not working right now.')
  })

  test('Enter runs the full search at once and shows the answer beside the page', async () => {
    const { calls } = api()
    start()
    setPrompt('policy number')
    press('Enter')
    await wait(0)
    expect(searches(calls, true)).toHaveLength(1)
    expect(searches(calls, true)[0]?.body).toEqual({ prompt: 'policy number', full: true })
    const panel = screen.getByRole('region', { name: 'Answer' })
    expect(within(panel).getByText('P/21/2138/5675525')).toBeInTheDocument()
    expect(
      within(panel).getByText(/Kavita Rao\/Insurance\/2026-09-20 Health policy/),
    ).toBeInTheDocument()
    expect(within(panel).getByText(/Page 1/)).toBeInTheDocument()
    expect(within(panel).getByRole('button', { name: 'Open at page' })).toBeInTheDocument()
    expect(within(panel).getByRole('button', { name: 'Show in folder' })).toBeInTheDocument()
    expect(within(panel).getByRole('img', { name: /Page 1/ })).toHaveAttribute(
      'src',
      expect.stringContaining('/v1/documents/doc-a/pages/0.png'),
    )
  })

  test('the full search also runs 600 ms after the last key, and the answer waits for it', async () => {
    const { calls } = api()
    start()
    setPrompt('policy number')
    await wait(150)
    expect(screen.queryByRole('region', { name: 'Answer' })).not.toBeInTheDocument()
    await wait(449)
    expect(searches(calls, true)).toHaveLength(0)
    await wait(1)
    expect(searches(calls, true)).toHaveLength(1)
    expect(screen.getByRole('region', { name: 'Answer' })).toBeInTheDocument()
  })

  test('an outlined line is a button that opens the viewer at that line', async () => {
    api()
    start()
    setPrompt('policy number')
    press('Enter')
    await wait(0)
    const outline = screen.getByRole('button', { name: 'Line 4: Policy Number' })
    fireEvent.click(outline)
    expect(window.location.pathname).toBe('/doc/doc-a')
    expect(window.location.search).toBe('?page=1&lines=3')
  })

  test('Open at page opens the viewer at the answer page and its lines', async () => {
    api()
    start()
    setPrompt('policy number')
    press('Enter')
    await wait(0)
    fireEvent.click(screen.getByRole('button', { name: 'Open at page' }))
    expect(window.location.pathname + window.location.search).toBe('/doc/doc-a?page=1&lines=3')
  })

  test('an ID number is masked until Show is pressed', async () => {
    api({
      full: {
        body: search({
          rows: [
            row({
              doc_type: 'aadhaar',
              key_fields: { holder: 'Kavita Rao', number: '2345 6789 0123' },
            }),
          ],
          answer: answer({
            field: 'number',
            text: '2345 6789 0123',
            value: '2345 6789 0123',
            masked: true,
          }),
        }),
      },
    })
    start()
    setPrompt('aadhaar')
    press('Enter')
    await wait(0)
    const panel = screen.getByRole('region', { name: 'Answer' })
    expect(within(panel).getByText('•••• 0123')).toBeInTheDocument()
    expect(screen.queryByText('2345 6789 0123')).not.toBeInTheDocument()
    // the finder row masks it too, with no way to show it there
    expect(screen.getByRole('option', { name: /0123/ })).not.toHaveTextContent('2345')
    fireEvent.click(within(panel).getByRole('button', { name: 'Show number' }))
    expect(within(panel).getByText('2345 6789 0123')).toBeInTheDocument()
  })

  test('no direct answer shows the closest files', async () => {
    api({
      full: {
        body: search({
          rows: [row(), row({ document_id: 'doc-b', rel_path: 'Other/File.pdf' })],
          no_answer: noAnswer({ reason: 'weak_match', closest: [row().rel_path] }),
        }),
      },
    })
    start()
    setPrompt('anil')
    press('Enter')
    await wait(0)
    expect(screen.getByText('No direct answer.')).toBeInTheDocument()
    expect(screen.queryByRole('region', { name: 'Answer' })).not.toBeInTheDocument()
    const options = screen.getAllByRole('option')
    expect(options).toHaveLength(1)
    expect(options[0]).toHaveTextContent('Health policy')
  })

  test('no direct answer names the person it could not find', async () => {
    api({
      full: {
        body: search({
          rows: [],
          query: {
            intent: 'lookup',
            people: [],
            types: [],
            areas: [],
            field: null,
            role: null,
            range: null,
            place: null,
            words: '',
            unread: ['Anil'],
          },
          no_answer: noAnswer({ reason: 'unknown_person', closest: [] }),
        }),
      },
    })
    start()
    setPrompt('anil policy')
    press('Enter')
    await wait(0)
    expect(screen.getByText('No direct answer.')).toBeInTheDocument()
    expect(screen.getByText('No one called Anil is in the household.')).toBeInTheDocument()
  })

  test('the model-off line shows and keyword rows still come', async () => {
    api({
      quick: { body: search({ reading: 'off' }) },
      full: { body: search({ reading: 'off' }) },
    })
    start()
    setPrompt('care')
    await wait(150)
    expect(
      screen.getByText(
        "Reading prompts needs the local model, which isn't running. Showing keyword matches.",
      ),
    ).toBeInTheDocument()
    expect(screen.getAllByRole('option')).toHaveLength(1)
  })

  test('a card row says where the number is kept, and nothing about it is fetched', async () => {
    const { calls } = api({
      quick: {
        body: search({ rows: [row({ doc_type: 'card_front', key_fields: { bank: 'HDFC' } })] }),
      },
    })
    start()
    setPrompt('card')
    await wait(150)
    expect(screen.getByRole('option')).toHaveTextContent(
      'The card number and CVV are kept in Secrets.kdbx and open with the master password.',
    )
    expect(calls.some((c) => c.path.includes('/file') || c.path.includes('secrets'))).toBe(false)
  })

  test('a card answer fetches no page, no lines and no file', async () => {
    const { calls } = api({
      full: {
        body: search({
          rows: [row({ doc_type: 'card_front', key_fields: { bank: 'HDFC' } })],
          answer: answer({ field: 'bank', text: 'HDFC', value: 'HDFC' }),
        }),
      },
    })
    start()
    setPrompt('card bank')
    press('Enter')
    await wait(0)
    expect(screen.getByRole('region', { name: 'Answer' })).toBeInTheDocument()
    expect(screen.queryByRole('img')).not.toBeInTheDocument()
    const paths = new Set(calls.map((c) => c.path))
    expect(
      [...paths].every((p) => ['/v1/search', '/v1/people', '/v1/needs-a-look'].includes(p)),
    ).toBe(true)
    expect(calls.some((c) => c.path.includes('/lines'))).toBe(false)
  })

  test('Enter tries a failed full search again', async () => {
    const replies: Searches = { full: { status: 500, body: { detail: 'The model is busy.' } } }
    const { calls } = api(replies)
    start()
    setPrompt('policy number')
    press('Enter')
    await wait(0)
    expect(screen.getByRole('alert')).toHaveTextContent('The model is busy.')
    delete replies.full
    press('Enter')
    await wait(0)
    expect(searches(calls, true)).toHaveLength(2)
    expect(screen.getByRole('region', { name: 'Answer' })).toBeInTheDocument()
    expect(screen.queryByText('The model is busy.')).not.toBeInTheDocument()
  })

  test('the Drive path note goes away when the prompt changes', async () => {
    api({ reveal: { status: 409, body: { detail: 'Not here.' } } })
    start()
    setPrompt('care')
    await wait(150)
    press('ArrowDown')
    press('Enter', { metaKey: true })
    await wait(0)
    expect(screen.getByRole('status')).toHaveTextContent('Drive path copied')
    setPrompt('care health')
    await wait(0)
    expect(screen.queryByText('Drive path copied')).not.toBeInTheDocument()
  })

  test('rows show amounts and dates the way the answer writes them', async () => {
    api({
      quick: {
        body: search({
          rows: [
            row({
              key_fields: {
                sum_insured: '1000000',
                end_date: '2027-09-19',
                policy_number: 'P/21/2138/5675525',
              },
              field_kinds: {
                sum_insured: 'amount',
                end_date: 'date',
                policy_number: 'identifier',
              },
            }),
          ],
        }),
      },
    })
    start()
    setPrompt('care')
    await wait(150)
    const option = screen.getByRole('option')
    expect(option).toHaveTextContent('Rs 10,00,000')
    expect(option).toHaveTextContent('19 Sep 2027')
    expect(option).toHaveTextContent('P/21/2138/5675525')
    expect(option).not.toHaveTextContent('2027-09-19')
  })

  test('Escape clears the box and the results', async () => {
    api()
    start()
    setPrompt('care')
    await wait(150)
    expect(screen.getAllByRole('option')).toHaveLength(1)
    press('Escape')
    expect(box()).toHaveValue('')
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
  })

  test('opens with the prompt in the address and searches it', async () => {
    open('/?q=care')
    const { calls } = api()
    render(<App />)
    await wait(150)
    expect(searches(calls)[0]?.body).toEqual({ prompt: 'care', full: false })
    expect(screen.getAllByRole('option')).toHaveLength(1)
  })
})

describe('the finder keyboard', () => {
  test('arrow keys move the active row and Enter opens the viewer at its page', async () => {
    api({
      quick: {
        body: search({
          rows: [
            row(),
            row({
              document_id: 'doc-b',
              rel_path: 'B/File.pdf',
              lines: [{ page: 1, idx: 7, bbox: [0.1, 0.1, 0.2, 0.2] }],
            }),
          ],
        }),
      },
    })
    start()
    setPrompt('care')
    await wait(150)
    const options = screen.getAllByRole('option')
    expect(box()).not.toHaveAttribute('aria-activedescendant')
    press('ArrowDown')
    expect(box()).toHaveAttribute('aria-activedescendant', options[0]!.id)
    expect(options[0]).toHaveAttribute('aria-selected', 'true')
    press('ArrowDown')
    expect(box()).toHaveAttribute('aria-activedescendant', options[1]!.id)
    press('ArrowUp')
    expect(box()).toHaveAttribute('aria-activedescendant', options[0]!.id)
    press('ArrowDown')
    press('Enter')
    expect(window.location.pathname + window.location.search).toBe('/doc/doc-b?page=2&lines=7')
  })

  test('Cmd+Enter shows the file in its folder, and copies the Drive path when the Mac says no', async () => {
    const { calls } = api({
      reveal: {
        status: 409,
        body: {
          detail: 'Show in folder works on the Mac itself, so the Drive path was copied instead.',
        },
      },
    })
    start()
    setPrompt('care')
    await wait(150)
    press('ArrowDown')
    press('Enter', { metaKey: true })
    await wait(0)
    const reveal = calls.find((c) => c.path === '/v1/documents/doc-a/reveal')
    expect(reveal?.method).toBe('POST')
    expect(await navigator.clipboard.readText()).toBe(row().drive_path)
    expect(screen.getByRole('status')).toHaveTextContent('Drive path copied')
    // the search was not run again by the shortcut
    expect(searches(calls, true)).toHaveLength(0)
  })

  test('Show in folder on the Mac says it opened the folder', async () => {
    const { calls } = api()
    start()
    setPrompt('policy number')
    press('Enter')
    await wait(0)
    fireEvent.click(screen.getByRole('button', { name: 'Show in folder' }))
    await wait(0)
    expect(calls.some((c) => c.path === '/v1/documents/doc-a/reveal')).toBe(true)
    expect(screen.getByRole('status')).toHaveTextContent('Opened the folder.')
  })

  test('a refusal that is not the Mac saying no shows the sentence it gave', async () => {
    api({ reveal: { status: 404, body: { detail: 'That file is not available.' } } })
    start()
    setPrompt('care')
    await wait(150)
    press('ArrowDown')
    press('Enter', { ctrlKey: true })
    await wait(0)
    expect(screen.getByRole('alert')).toHaveTextContent('That file is not available.')
  })
})

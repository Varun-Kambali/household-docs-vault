import { act, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'

import { App } from '../app/App.tsx'
import { LINES, PEOPLE, document, stubApi, type Call, type Reply } from '../test/api.ts'

const page_document = window.document

function open(path: string): void {
  window.history.replaceState(null, '', path)
}

type Replies = { doc?: Reply; reveal?: Reply; lines?: Reply }

function api(replies: Replies = {}) {
  return stubApi((call: Call): Reply | undefined => {
    if (call.path === '/v1/needs-a-look') return { body: [] }
    if (call.path === '/v1/people') return { body: PEOPLE }
    if (call.path.endsWith('/lines')) return replies.lines ?? { body: LINES }
    if (call.path === '/v1/documents/doc-a') return replies.doc ?? { body: document() }
    if (call.path.endsWith('/reveal')) return replies.reveal ?? { status: 204 }
    return undefined
  })
}

// A page scrolls into view: the observers the viewer made are told so.
const watchers: { callback: IntersectionObserverCallback; seen: Set<Element> }[] = []
class FakeObserver {
  private readonly entry: { callback: IntersectionObserverCallback; seen: Set<Element> }
  constructor(callback: IntersectionObserverCallback) {
    this.entry = { callback, seen: new Set() }
    watchers.push(this.entry)
  }
  observe(element: Element): void {
    this.entry.seen.add(element)
  }
  unobserve(): void {}
  disconnect(): void {}
  takeRecords(): IntersectionObserverEntry[] {
    return []
  }
}

function scrollTo(pageNumber: number): void {
  const frame = screen.getByTestId(`page-${pageNumber}`)
  act(() => {
    for (const watcher of watchers) {
      if (watcher.seen.has(frame)) {
        watcher.callback(
          [{ isIntersecting: true, target: frame } as unknown as IntersectionObserverEntry],
          {} as IntersectionObserver,
        )
      }
    }
  })
}

const images = () => screen.queryAllByRole('img').filter((el) => el.tagName === 'IMG')

async function flush(): Promise<void> {
  await act(async () => {
    await Promise.resolve()
  })
}

beforeEach(() => {
  watchers.length = 0
  vi.stubGlobal('IntersectionObserver', FakeObserver)
  const written: string[] = []
  vi.stubGlobal('navigator', {
    ...window.navigator,
    clipboard: {
      writeText: (text: string) => {
        written.push(text)
        return Promise.resolve()
      },
    },
  })
})
afterEach(() => {
  vi.unstubAllGlobals()
  open('/')
})

describe('the page viewer', () => {
  test('shows the document, loads the open page and the others as they come into view', async () => {
    open('/doc/doc-a?page=1&lines=3')
    api()
    render(<App />)
    await flush()
    expect(screen.getByRole('heading', { level: 1, name: 'Health policy' })).toBeInTheDocument()
    expect(screen.getByText(/Kavita Rao\/Insurance\/2026-09-20 Health policy/)).toBeInTheDocument()
    // two pages are laid out; only the open one has loaded its image
    expect(screen.getByTestId('page-1')).toBeInTheDocument()
    expect(screen.getByTestId('page-2')).toBeInTheDocument()
    expect(images().map((img) => img.getAttribute('src'))).toEqual([
      expect.stringContaining('/v1/documents/doc-a/pages/0.png'),
    ])
    scrollTo(2)
    expect(images().map((img) => img.getAttribute('src'))).toEqual([
      expect.stringContaining('/v1/documents/doc-a/pages/0.png'),
      expect.stringContaining('/v1/documents/doc-a/pages/1.png'),
    ])
  })

  test('Left and Right move between pages and the address follows', async () => {
    open('/doc/doc-a?page=1')
    api()
    render(<App />)
    await flush()
    fireEvent.keyDown(pageBody(), { key: 'ArrowRight' })
    expect(window.location.search).toBe('?page=2')
    fireEvent.keyDown(pageBody(), { key: 'ArrowRight' })
    expect(window.location.search).toBe('?page=2')
    fireEvent.keyDown(pageBody(), { key: 'ArrowLeft' })
    expect(window.location.search).toBe('?page=1')
    fireEvent.keyDown(pageBody(), { key: 'ArrowLeft' })
    expect(window.location.search).toBe('?page=1')
  })

  test('outlines the lines in the address, each a button named by its line', async () => {
    open('/doc/doc-a?page=1&lines=3,4')
    api()
    render(<App />)
    await flush()
    const first = screen.getByRole('button', { name: 'Line 4: Policy Number' })
    expect(screen.getByRole('button', { name: 'Line 5: P/21/2138/5675525' })).toBeInTheDocument()
    fireEvent.click(first)
    expect(window.location.search).toBe('?page=1&lines=3')
    expect(screen.queryByRole('button', { name: /^Line 5/ })).not.toBeInTheDocument()
  })

  test('fit width and 100% are a two-option control', async () => {
    open('/doc/doc-a?page=1')
    api()
    render(<App />)
    await flush()
    const group = screen.getByRole('radiogroup', { name: 'Page size' })
    const fit = within(group).getByRole('radio', { name: 'Fit width' })
    const full = within(group).getByRole('radio', { name: '100%' })
    expect(fit).toBeChecked()
    fireEvent.click(full)
    expect(full).toBeChecked()
    expect(screen.getByTestId('page-1')).toHaveAttribute('data-size', 'actual')
    expect(images()[0]?.getAttribute('src')).toContain('width=1600')
  })

  test('Show in folder opens it, or copies the Drive path when the Mac says no', async () => {
    open('/doc/doc-a?page=1')
    const { calls } = api({ reveal: { status: 409, body: { detail: 'Not here.' } } })
    render(<App />)
    await flush()
    fireEvent.click(screen.getByRole('button', { name: 'Show in folder' }))
    await flush()
    expect(calls.some((c) => c.path === '/v1/documents/doc-a/reveal' && c.method === 'POST')).toBe(
      true,
    )
    expect(screen.getByRole('status')).toHaveTextContent('Drive path copied')
  })

  test('Download original is the raw file as an attachment', async () => {
    open('/doc/doc-a?page=1')
    api()
    render(<App />)
    await flush()
    const link = screen.getByRole('link', { name: 'Download original' })
    expect(link).toHaveAttribute('href', '/v1/documents/doc-a/file')
    expect(link).toHaveAttribute('download')
  })

  test('lists the stored fields, and an ID number is masked until Show', async () => {
    open('/doc/doc-a?page=1')
    api({
      doc: {
        body: document({
          doc_type: 'aadhaar',
          fields: { holder: 'Kavita Rao', number: '2345 6789 0123' },
          field_kinds: { holder: 'text', number: 'identifier' },
        }),
      },
    })
    render(<App />)
    await flush()
    expect(screen.getByText('Kavita Rao', { selector: 'dd' })).toBeInTheDocument()
    expect(screen.queryByText('2345 6789 0123')).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Show number' }))
    expect(screen.getByText('2345 6789 0123')).toBeInTheDocument()
  })

  test("field names are the vault's own labels, with a fallback for any other", async () => {
    open('/doc/doc-a?page=1')
    api({
      doc: {
        body: document({
          doc_type: 'card_statement',
          fields: { last4: '4242', bank: 'HDFC', odd_thing: 'x' },
          field_kinds: {},
        }),
      },
    })
    render(<App />)
    await flush()
    expect(screen.getByText('Last four digits', { selector: 'dt' })).toBeInTheDocument()
    expect(screen.getByText('Bank', { selector: 'dt' })).toBeInTheDocument()
    expect(screen.getByText('Odd thing', { selector: 'dt' })).toBeInTheDocument()
  })

  test('a card does not offer Download original, as the server refuses its raw bytes', async () => {
    for (const docType of ['card_front', 'card_statement', 'card_welcome_letter']) {
      open('/doc/doc-a?page=1')
      api({ doc: { body: document({ doc_type: docType, fields: { bank: 'HDFC' } }) } })
      const view = render(<App />)
      await flush()
      expect(screen.getByRole('button', { name: 'Show in folder' })).toBeInTheDocument()
      expect(screen.queryByRole('link', { name: 'Download original' })).not.toBeInTheDocument()
      view.unmount()
    }
  })

  test('a card says where its number is kept', async () => {
    open('/doc/doc-a?page=1')
    api({ doc: { body: document({ doc_type: 'card_front', fields: { bank: 'HDFC' } }) } })
    render(<App />)
    await flush()
    expect(
      screen.getByText(
        'The card number and CVV are kept in Secrets.kdbx and open with the master password.',
      ),
    ).toBeInTheDocument()
  })

  test('says so when the file is not there, and while it loads', async () => {
    open('/doc/doc-a?page=1')
    api({ doc: { status: 404, body: { detail: 'That file is not available.' } } })
    render(<App />)
    expect(screen.getByRole('heading', { level: 1 })).toBeInTheDocument()
    expect(screen.getByRole('status')).toHaveTextContent('Loading the document')
    await flush()
    expect(screen.getByRole('alert')).toHaveTextContent('That file is not available.')
  })

  test('a page that cannot be drawn says so in its place', async () => {
    open('/doc/doc-a?page=1')
    api()
    render(<App />)
    await flush()
    fireEvent.error(images()[0]!)
    expect(screen.getByText('This page cannot be shown.')).toBeInTheDocument()
  })

  test('scrolls the cited box into view once the lines arrive, smoothly unless motion is reduced', async () => {
    open('/doc/doc-a?page=1&lines=4')
    api()
    const scrolled: { element: Element; options: unknown }[] = []
    const original = Element.prototype.scrollIntoView
    Element.prototype.scrollIntoView = function (this: Element, options?: unknown) {
      scrolled.push({ element: this, options })
    }
    try {
      render(<App />)
      await flush()
      const box = screen.getByRole('button', { name: 'Line 5: P/21/2138/5675525' })
      const last = scrolled.at(-1)
      expect(last?.element).toBe(box)
      expect(last?.options).toEqual({ block: 'center', behavior: 'smooth' })
    } finally {
      Element.prototype.scrollIntoView = original
    }
  })

  test('does not animate the scroll when the person asked for reduced motion', async () => {
    open('/doc/doc-a?page=1&lines=4')
    api()
    vi.stubGlobal('matchMedia', (query: string) => ({
      matches: query.includes('prefers-reduced-motion'),
      media: query,
    }))
    const scrolled: { element: Element; options: unknown }[] = []
    const original = Element.prototype.scrollIntoView
    Element.prototype.scrollIntoView = function (this: Element, options?: unknown) {
      scrolled.push({ element: this, options })
    }
    try {
      render(<App />)
      await flush()
      const box = screen.getByRole('button', { name: 'Line 5: P/21/2138/5675525' })
      expect(scrolled.at(-1)?.element).toBe(box)
      expect(scrolled.at(-1)?.options).toEqual({ block: 'center', behavior: 'auto' })
    } finally {
      Element.prototype.scrollIntoView = original
    }
  })

  test('at 100% the pages still load only as they come into view', async () => {
    open('/doc/doc-a?page=1')
    api()
    render(<App />)
    await flush()
    fireEvent.click(screen.getByRole('radio', { name: '100%' }))
    expect(images()).toHaveLength(1)
    scrollTo(2)
    expect(images()).toHaveLength(2)
  })

  test('Download original saves under the file own name', async () => {
    open('/doc/doc-a?page=1')
    api()
    render(<App />)
    await flush()
    expect(screen.getByRole('link', { name: 'Download original' })).toHaveAttribute(
      'download',
      '2026-09-20 Health policy - Care Health.pdf',
    )
  })

  test('shows amounts and dates the way the answer writes them, identifiers as stored', async () => {
    open('/doc/doc-a?page=1')
    api({
      doc: {
        body: document({
          fields: {
            sum_insured: '1000000',
            end_date: '2027-09-19',
            policy_number: 'P/21/2138/5675525',
          },
          field_kinds: { sum_insured: 'amount', end_date: 'date', policy_number: 'identifier' },
        }),
      },
    })
    render(<App />)
    await flush()
    expect(screen.getByText('Rs 10,00,000', { selector: 'dd' })).toBeInTheDocument()
    expect(screen.getByText('19 Sep 2027', { selector: 'dd' })).toBeInTheDocument()
    const id = screen.getByText('P/21/2138/5675525', { selector: 'dd' })
    expect(id).toHaveClass('identifier')
  })

  test('Escape returns to the results', async () => {
    open('/doc/doc-a?page=1')
    api()
    vi.spyOn(window.history, 'length', 'get').mockReturnValue(3)
    const back = vi.spyOn(window.history, 'back').mockImplementation(() => undefined)
    render(<App />)
    await flush()
    fireEvent.keyDown(pageBody(), { key: 'Escape' })
    expect(back).toHaveBeenCalled()
  })

  test('Escape with nowhere to go back to opens Search', async () => {
    open('/doc/doc-a?page=1')
    api()
    render(<App />)
    await flush()
    fireEvent.keyDown(pageBody(), { key: 'Escape' })
    expect(window.location.pathname).toBe('/')
  })
})

function pageBody(): HTMLElement {
  return window.document.body
}

test('the title is the kind of document', async () => {
  open('/doc/doc-a?page=1')
  api()
  render(<App />)
  await flush()
  expect(page_document.title).toBe('Health policy - Household vault')
})

test('the field the answer came from is marked, and only that one', async () => {
  open('/doc/doc-a?page=1&lines=4&field=policy_number')
  api()
  render(<App />)
  await flush()
  const marked = page_document.querySelectorAll('.field[aria-current="true"]')
  expect(marked).toHaveLength(1)
  expect(marked[0]).toHaveTextContent('Policy number')
})

test('with no field in the address nothing is marked', async () => {
  open('/doc/doc-a?page=1')
  api()
  render(<App />)
  await flush()
  expect(page_document.querySelectorAll('.field[aria-current]')).toHaveLength(0)
})

test('the inspector is headed by the kind of document, with the file name as a caption', async () => {
  open('/doc/doc-a?page=1')
  api()
  render(<App />)
  await flush()
  const panel = screen.getByRole('complementary', { name: 'About this file' })
  expect(within(panel).getByRole('heading', { name: 'Health policy' })).toBeInTheDocument()
  expect(within(panel).getByText(/2026-09-20 Health policy - Care Health\.pdf/)).toHaveClass(
    'inspector-path',
  )
})

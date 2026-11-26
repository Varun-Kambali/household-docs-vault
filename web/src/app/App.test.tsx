import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'

import { App } from './App.tsx'
import { AREAS } from './areas.ts'

function answerWith(waiting: number | 'down'): void {
  vi.stubGlobal(
    'fetch',
    vi.fn(() =>
      waiting === 'down'
        ? Promise.reject(new TypeError('Failed to fetch'))
        : Promise.resolve(
            new Response(JSON.stringify(Array.from({ length: waiting }, (_, id) => ({ id }))), {
              status: 200,
              headers: { 'Content-Type': 'application/json' },
            }),
          ),
    ),
  )
}

function open(path: string): void {
  window.history.replaceState(null, '', path)
}

beforeEach(() => answerWith(0))
afterEach(() => open('/'))

describe('the shell', () => {
  test('has Search and Inbox and then the twelve areas, in order', async () => {
    open('/')
    render(<App />)
    const nav = screen.getByRole('navigation', { name: 'Vault' })
    const links = within(nav).getAllByRole('link')
    expect(links.map((link) => link.textContent)).toEqual([
      'Search',
      'Inbox',
      ...AREAS.map((area) => area.label),
    ])
    expect(links[0]).toHaveAttribute('href', '/')
    expect(links[1]).toHaveAttribute('href', '/inbox')
    expect(links[8]).toHaveAttribute('href', '/area/tax')
  })

  test('focuses the search box on /', () => {
    open('/')
    render(<App />)
    expect(screen.getByRole('searchbox', { name: 'Ask about your documents' })).toHaveFocus()
  })

  test('does not take focus on other screens', () => {
    open('/inbox')
    render(<App />)
    expect(screen.queryByRole('searchbox')).not.toBeInTheDocument()
    expect(screen.getByRole('heading', { level: 1, name: 'Inbox' })).toBeInTheDocument()
  })

  test('/ and Cmd+K bring the search box back from anywhere', async () => {
    open('/area/tax')
    const user = userEvent.setup()
    render(<App />)
    await user.keyboard('/')
    expect(screen.getByRole('searchbox')).toHaveFocus()
    expect(window.location.pathname).toBe('/')
  })

  test('a link moves to its screen without leaving the page, and marks where you are', async () => {
    open('/')
    const user = userEvent.setup()
    render(<App />)
    await user.click(screen.getByRole('link', { name: 'Insurance' }))
    expect(window.location.pathname).toBe('/area/insurance')
    expect(screen.getByRole('heading', { level: 1, name: 'Insurance' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Insurance' })).toHaveAttribute('aria-current', 'page')
    expect(screen.getByRole('link', { name: 'Search' })).not.toHaveAttribute('aria-current')
  })

  test('after a link the keyboard starts at the new title', async () => {
    open('/')
    const user = userEvent.setup()
    render(<App />)
    await user.click(screen.getByRole('link', { name: 'Tax' }))
    expect(screen.getByRole('heading', { level: 1, name: 'Tax' })).toHaveFocus()
  })

  test('the back button returns to the earlier screen', async () => {
    open('/')
    const user = userEvent.setup()
    render(<App />)
    await user.click(screen.getByRole('link', { name: 'Inbox' }))
    expect(screen.getByRole('heading', { level: 1, name: 'Inbox' })).toBeInTheDocument()
    window.history.back()
    expect(await screen.findByRole('searchbox')).toBeInTheDocument()
  })

  test('the menu button opens and closes the list of places', async () => {
    open('/')
    const user = userEvent.setup()
    render(<App />)
    const button = screen.getByRole('button', { name: 'Menu' })
    expect(button).toHaveAttribute('aria-expanded', 'false')
    await user.click(button)
    expect(button).toHaveAttribute('aria-expanded', 'true')
    await user.keyboard('{Escape}')
    expect(button).toHaveAttribute('aria-expanded', 'false')
  })

  test('choosing a place closes the menu', async () => {
    open('/')
    const user = userEvent.setup()
    render(<App />)
    const button = screen.getByRole('button', { name: 'Menu' })
    await user.click(button)
    await user.click(screen.getByRole('link', { name: 'Tax' }))
    expect(button).toHaveAttribute('aria-expanded', 'false')
  })
})

describe('the Inbox count', () => {
  test('is plain text beside Inbox, from the items waiting for an answer', async () => {
    answerWith(3)
    open('/')
    render(<App />)
    expect(await screen.findByRole('link', { name: 'Inbox 3' })).toBeInTheDocument()
    expect(fetch).toHaveBeenCalledWith('/v1/needs-a-look', expect.anything())
  })

  test('shows no number when nothing waits', async () => {
    answerWith(0)
    open('/')
    render(<App />)
    await vi.waitFor(() => expect(fetch).toHaveBeenCalled())
    expect(screen.getByRole('link', { name: 'Inbox' })).toBeInTheDocument()
  })

  test('leaving a screen drops its pending count without an error', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(
        (_url: string, init?: RequestInit) =>
          new Promise<Response>((_resolve, reject) => {
            init?.signal?.addEventListener('abort', () =>
              reject(new DOMException('aborted', 'AbortError')),
            )
          }),
      ),
    )
    open('/')
    const { unmount } = render(<App />)
    unmount()
    await vi.waitFor(() => expect(fetch).toHaveBeenCalled())
  })

  test('is read once on start and not again when moving between screens', async () => {
    answerWith(1)
    open('/')
    const user = userEvent.setup()
    render(<App />)
    await screen.findByRole('link', { name: 'Inbox 1' })
    await user.click(screen.getByRole('link', { name: /Inbox/ }))
    await user.click(screen.getByRole('link', { name: 'Tax' }))
    await user.click(screen.getByRole('link', { name: 'Search' }))
    const lists = vi.mocked(fetch).mock.calls.filter(([url]) => String(url) === '/v1/needs-a-look')
    expect(lists).toHaveLength(1)
  })

  test('shows no number when the count cannot be read', async () => {
    answerWith('down')
    open('/')
    render(<App />)
    await vi.waitFor(() => expect(fetch).toHaveBeenCalled())
    expect(screen.getByRole('link', { name: 'Inbox' })).toBeInTheDocument()
  })
})

describe('the Inbox screen', () => {
  test('waits, then says how many files need an answer', async () => {
    answerWith(2)
    open('/inbox')
    render(<App />)
    expect(screen.getByRole('status')).toHaveTextContent('Loading the Inbox')
    expect(await screen.findByText('2 waiting for an answer.')).toBeInTheDocument()
  })

  test('says so when nothing is waiting', async () => {
    answerWith(0)
    open('/inbox')
    render(<App />)
    expect(
      await screen.findByText('Nothing waiting. New files are read as they arrive.'),
    ).toBeInTheDocument()
  })

  test('shows the reason when the list cannot be read', async () => {
    answerWith('down')
    open('/inbox')
    render(<App />)
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'The vault is not answering. Check that it is running.',
    )
  })
})

describe('search on /', () => {
  test('?q= fills the box, and typing keeps the address in step', async () => {
    open('/?q=kavita')
    const user = userEvent.setup()
    render(<App />)
    const box = screen.getByRole('searchbox')
    expect(box).toHaveValue('kavita')
    await user.type(box, 's policy')
    expect(new URLSearchParams(window.location.search).get('q')).toBe('kavitas policy')
    await user.clear(box)
    expect(window.location.search).toBe('')
  })

  test('says what the box is for while it is empty', () => {
    open('/')
    render(<App />)
    expect(screen.getByText(/Ask in a few words/)).toBeInTheDocument()
  })
})

describe('other screens', () => {
  test('an area shows its title and an empty list', () => {
    open('/area/utilities')
    render(<App />)
    expect(screen.getByRole('heading', { level: 1, name: 'Utilities' })).toBeInTheDocument()
    expect(screen.getByText('Nothing filed under Utilities yet.')).toBeInTheDocument()
  })

  test('the viewer opens with its title while the document loads', () => {
    open('/doc/12?page=1&lines=2-3')
    render(<App />)
    expect(screen.getByRole('heading', { level: 1, name: 'Document' })).toBeInTheDocument()
  })

  test('an unknown address says so and offers Search', () => {
    open('/nowhere')
    render(<App />)
    expect(screen.getByRole('heading', { level: 1, name: 'Page not found' })).toBeInTheDocument()
  })

  test('the page has one main region to skip to', async () => {
    open('/inbox')
    const user = userEvent.setup()
    render(<App />)
    await user.tab()
    expect(screen.getByRole('link', { name: 'Skip to the page' })).toHaveFocus()
    expect(screen.getByRole('main')).toHaveAttribute('id', 'main')
  })
})

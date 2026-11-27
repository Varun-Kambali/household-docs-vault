import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, test, vi } from 'vitest'

import type { ActivityOut } from '../api/types.ts'
import { activityEntry, stubApi } from '../test/api.ts'
import { Activity } from './Activity.tsx'

afterEach(() => window.history.replaceState(null, '', '/'))

const OLDER = activityEntry({
  id: 4,
  step: 'read',
  detail: 'Read 2 pages',
  actions: [],
  document_id: null,
  file: 'Inbox/older.pdf',
})

describe('Activity', () => {
  test("an item's newest entry shows its actions and Undo calls the API", async () => {
    const { calls } = stubApi((call) =>
      call.path.startsWith('/v1/activity')
        ? { body: [activityEntry(), { ...OLDER, item_id: 7 }] }
        : call.path === '/v1/documents/doc-a/undo'
          ? { body: { id: 7, state: 'queued' } }
          : undefined,
    )
    const onChanged = vi.fn<(id?: number) => void>()
    const user = userEvent.setup()
    render(<Activity version={0} onChanged={onChanged} onShow={vi.fn<(id?: number) => void>()} />)
    const rows = await screen.findAllByRole('listitem')
    expect(rows).toHaveLength(2)
    // The newest entry for item 7 carries the actions; the older one does not repeat them.
    expect(within(rows[0]!).getByRole('link', { name: 'Open' })).toHaveAttribute(
      'href',
      '/doc/doc-a',
    )
    expect(within(rows[1]!).queryByRole('button')).not.toBeInTheDocument()
    expect(within(rows[0]!).getByText('Filed as Prescription')).toBeInTheDocument()
    expect(within(rows[0]!).getByText('Filed')).toBeInTheDocument()
    expect(within(rows[0]!).getByText(/Kavita Rao\/Health/)).toBeInTheDocument()
    await user.click(within(rows[0]!).getByRole('button', { name: 'Undo' }))
    expect(calls.some((c) => c.method === 'POST' && c.path === '/v1/documents/doc-a/undo')).toBe(
      true,
    )
    expect(onChanged).toHaveBeenCalled()
  })

  test('an asked file is undone through its item, retry goes through the items route', async () => {
    const asked = activityEntry({
      id: 20,
      item_id: 8,
      step: 'needs_a_look',
      detail: 'Whose is it?',
      document_id: null,
      actions: ['open', 'undo', 'answer'],
    })
    const held = activityEntry({
      id: 21,
      item_id: 9,
      step: 'error',
      detail: 'Held after an error',
      document_id: null,
      actions: ['retry'],
    })
    const { calls } = stubApi((call) =>
      call.path.startsWith('/v1/activity')
        ? { body: [held, asked] }
        : call.method === 'POST'
          ? { body: { id: 1, state: 'queued' } }
          : undefined,
    )
    const user = userEvent.setup()
    const onShow = vi.fn<(id?: number) => void>()
    render(<Activity version={0} onChanged={vi.fn<(id?: number) => void>()} onShow={onShow} />)
    await user.click(await screen.findByRole('button', { name: 'Retry' }))
    await user.click(screen.getByRole('button', { name: 'Undo' }))
    expect(calls.filter((c) => c.method === 'POST').map((c) => c.path)).toEqual([
      '/v1/items/9/retry',
      '/v1/needs-a-look/8/undo',
    ])
    // Open on a file that is still waiting shows its pages in the list above.
    await user.click(screen.getByRole('button', { name: 'Open' }))
    expect(onShow).toHaveBeenCalledWith(8)
  })

  test('shows an API refusal as the sentence it is', async () => {
    stubApi((call) =>
      call.path.startsWith('/v1/activity')
        ? { body: [activityEntry()] }
        : { status: 409, body: { detail: 'A file with that name is already in Inbox. Move or rename it, then try Undo again.' } },
    )
    const user = userEvent.setup()
    render(
      <Activity
        version={0}
        onChanged={vi.fn<(id?: number) => void>()}
        onShow={vi.fn<(id?: number) => void>()}
      />,
    )
    await user.click(await screen.findByRole('button', { name: 'Undo' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('already in Inbox')
  })

  test('Show older pages with before, and is gone when a page comes back short', async () => {
    const page = (first: number, n: number): ActivityOut[] =>
      Array.from({ length: n }, (_, i) =>
        activityEntry({ id: first - i, item_id: null, actions: [], document_id: null }),
      )
    const { calls } = stubApi((call) => {
      if (call.path === '/v1/activity?limit=20') return { body: page(50, 20) }
      if (call.path === '/v1/activity?limit=20&before=31') return { body: page(30, 3) }
      return undefined
    })
    const user = userEvent.setup()
    render(
      <Activity
        version={0}
        onChanged={vi.fn<(id?: number) => void>()}
        onShow={vi.fn<(id?: number) => void>()}
      />,
    )
    await user.click(await screen.findByRole('button', { name: 'Show older' }))
    expect(calls.at(-1)?.path).toBe('/v1/activity?limit=20&before=31')
    expect(await screen.findAllByRole('listitem')).toHaveLength(23)
    expect(screen.queryByRole('button', { name: 'Show older' })).not.toBeInTheDocument()
  })

  test('says so when nothing has happened yet, and reads again when the version changes', async () => {
    const { calls } = stubApi(() => ({ body: [] }))
    const { rerender } = render(
      <Activity
        version={0}
        onChanged={vi.fn<(id?: number) => void>()}
        onShow={vi.fn<(id?: number) => void>()}
      />,
    )
    expect(await screen.findByText('Nothing has happened yet.')).toBeInTheDocument()
    rerender(
      <Activity
        version={1}
        onChanged={vi.fn<(id?: number) => void>()}
        onShow={vi.fn<(id?: number) => void>()}
      />,
    )
    await screen.findByText('Nothing has happened yet.')
    expect(calls.filter((c) => c.path.startsWith('/v1/activity'))).toHaveLength(2)
  })

  test('shows the reason when it cannot be read', async () => {
    stubApi(() => ({ status: 500, body: { detail: 'Something went wrong. Nothing was changed.' } }))
    render(
      <Activity
        version={0}
        onChanged={vi.fn<(id?: number) => void>()}
        onShow={vi.fn<(id?: number) => void>()}
      />,
    )
    expect(await screen.findByRole('alert')).toHaveTextContent('Something went wrong')
  })

  test('a refused Show older says why and keeps what is shown', async () => {
    const page = Array.from({ length: 20 }, (_, i) =>
      activityEntry({ id: 50 - i, item_id: null, actions: [], document_id: null }),
    )
    stubApi((call) =>
      call.path.includes('before')
        ? { status: 500, body: { detail: 'Something went wrong. Nothing was changed.' } }
        : { body: page },
    )
    const user = userEvent.setup()
    render(<Activity version={0} onChanged={vi.fn<() => void>()} onShow={vi.fn<() => void>()} />)
    await user.click(await screen.findByRole('button', { name: 'Show older' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Something went wrong')
    expect(screen.getAllByRole('listitem')).toHaveLength(20)
  })

  test('older pages stay when the first page is read again', async () => {
    const head = (top: number) =>
      Array.from({ length: 20 }, (_, i) =>
        activityEntry({ id: top - i, item_id: null, actions: [], document_id: null }),
      )
    let first = 0
    stubApi((call) => {
      if (call.path.includes('before')) {
        return { body: [activityEntry({ id: 5, item_id: null, actions: [], document_id: null })] }
      }
      return { body: head(first++ === 0 ? 50 : 52) }
    })
    const user = userEvent.setup()
    const { rerender } = render(
      <Activity version={0} onChanged={vi.fn<() => void>()} onShow={vi.fn<() => void>()} />,
    )
    await user.click(await screen.findByRole('button', { name: 'Show older' }))
    expect(await screen.findAllByRole('listitem')).toHaveLength(21)
    rerender(<Activity version={1} onChanged={vi.fn<() => void>()} onShow={vi.fn<() => void>()} />)
    await vi.waitFor(() => expect(screen.getAllByRole('listitem')).toHaveLength(21))
    expect(screen.queryByRole('button', { name: 'Show older' })).not.toBeInTheDocument()
  })
})

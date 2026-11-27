import { act, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'

import type { ActivityOut } from '../api/types.ts'
import { activityEntry, stubApi } from '../test/api.ts'
import { FilingNotice, type Pending } from './FilingNotice.tsx'

beforeEach(() => vi.useFakeTimers({ shouldAdvanceTime: true }))
afterEach(() => vi.useRealTimers())

const NOW = Date.now()
const PENDING: Pending[] = [{ id: 7, name: 'prescription-1.pdf', at: NOW }]

function fresh(over: Partial<ActivityOut> = {}): ActivityOut {
  return activityEntry({ time: new Date(NOW + 1000).toISOString(), ...over })
}

function show(pending: Pending[], entries: ActivityOut[], onDone = vi.fn<(id: number) => void>()) {
  const onChanged = vi.fn<() => void>()
  const api = stubApi((call) => {
    if (call.path.startsWith('/v1/activity')) return { body: entries }
    if (call.method === 'POST') return { body: { id: 7, state: 'queued' } }
    return undefined
  })
  render(<FilingNotice pending={pending} version={0} onChanged={onChanged} onDone={onDone} />)
  return { onDone, onChanged, ...api }
}

describe('FilingNotice', () => {
  test('says the file is being filed until the log says where it went', async () => {
    show(PENDING, [fresh({ step: 'read', actions: [], document_id: null })])
    expect(await screen.findByText('Filing prescription-1.pdf')).toBeInTheDocument()
  })

  test('says where it went, with Undo for ten seconds', async () => {
    const { onDone, calls, onChanged } = show(PENDING, [fresh()])
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    expect(await screen.findByText('Filed in Kavita Rao / Health')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Undo' }))
    expect(calls.some((c) => c.method === 'POST' && c.path === '/v1/documents/doc-a/undo')).toBe(
      true,
    )
    expect(onChanged).toHaveBeenCalled()
    expect(onDone).toHaveBeenCalledWith(7)
  })

  test('the line goes after ten seconds, not before', async () => {
    const { onDone } = show(PENDING, [fresh()])
    await screen.findByText('Filed in Kavita Rao / Health')
    await act(async () => {
      await vi.advanceTimersByTimeAsync(9000)
    })
    expect(onDone).not.toHaveBeenCalled()
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1500)
    })
    expect(onDone).toHaveBeenCalledWith(7)
  })

  test('Cmd+Z undoes the last filing', async () => {
    const { calls } = show(PENDING, [fresh()])
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    await screen.findByText('Filed in Kavita Rao / Health')
    await user.keyboard('{Meta>}z{/Meta}')
    expect(calls.some((c) => c.path === '/v1/documents/doc-a/undo')).toBe(true)
  })

  test('says so when the file was discarded', async () => {
    show(PENDING, [
      fresh({ step: 'discarded', detail: 'Discarded', actions: [], document_id: null }),
    ])
    expect(await screen.findByText('Discarded prescription-1.pdf')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Undo' })).not.toBeInTheDocument()
  })

  test('an old entry is not taken for the answer to this one', async () => {
    show(PENDING, [activityEntry({ time: new Date(NOW - 3_600_000).toISOString() })])
    expect(await screen.findByText('Filing prescription-1.pdf')).toBeInTheDocument()
  })

  test('a file that is asked again leaves quietly: the list above has it', async () => {
    const { onDone } = show(PENDING, [
      fresh({ step: 'needs_a_look', actions: ['open', 'undo', 'answer'], document_id: null }),
    ])
    await vi.waitFor(() => expect(onDone).toHaveBeenCalledWith(7))
  })

  test('shows a refusal of Undo as the sentence it is', async () => {
    stubApi((call) =>
      call.path.startsWith('/v1/activity')
        ? { body: [fresh()] }
        : { status: 409, body: { detail: 'The filed copy moved. Nothing was changed.' } },
    )
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    render(
      <FilingNotice
        pending={PENDING}
        version={0}
        onChanged={vi.fn<() => void>()}
        onDone={vi.fn<(id: number) => void>()}
      />,
    )
    await user.click(await screen.findByRole('button', { name: 'Undo' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('The filed copy moved')
  })

  test('shows nothing when no file was answered', () => {
    const { calls } = show([], [])
    expect(calls).toHaveLength(0)
  })
})

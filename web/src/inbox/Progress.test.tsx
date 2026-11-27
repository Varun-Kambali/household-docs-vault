import { act, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'

import { idle, stubApi } from '../test/api.ts'
import type { ProgressOut } from '../api/types.ts'
import { Progress } from './Progress.tsx'
import { useProgress } from './useProgress.ts'

function Host() {
  const { progress, version } = useProgress()
  return (
    <>
      <Progress progress={progress} />
      <output data-testid="version">{version}</output>
    </>
  )
}

beforeEach(() => vi.useFakeTimers({ shouldAdvanceTime: false }))
afterEach(() => vi.useRealTimers())

async function tick(ms: number): Promise<void> {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms)
  })
}

describe('Progress', () => {
  test('progress polls every 2 s while work is queued and slows down when idle', async () => {
    const replies: ProgressOut[] = [
      idle({ waiting: 2, current: 'a.pdf', step: 'read', total_in_batch: 3, done_in_batch: 0 }),
      idle({ waiting: 1, current: 'b.pdf', step: 'read', total_in_batch: 3, done_in_batch: 1 }),
      idle({ total_in_batch: 3, done_in_batch: 3 }),
    ]
    const { calls } = stubApi(() => ({ body: replies[Math.min(calls.length - 1, 2)] }))
    render(<Host />)
    await tick(0)
    expect(calls).toHaveLength(1)
    expect(screen.getByText('Reading 1 of 3')).toBeInTheDocument()
    await tick(1999)
    expect(calls).toHaveLength(1)
    await tick(1)
    expect(calls).toHaveLength(2)
    expect(screen.getByText('Reading 2 of 3')).toBeInTheDocument()
    await tick(2000)
    expect(calls).toHaveLength(3)
    expect(screen.getByText('Read 3 of 3')).toBeInTheDocument()
    // Idle: it looks again every 10 s, in case a file was dropped.
    await tick(9999)
    expect(calls).toHaveLength(3)
    await tick(1)
    expect(calls).toHaveLength(4)
  })

  test('a file dropped while idle is noticed: idle, then busy, then idle again', async () => {
    const replies: ProgressOut[] = [
      idle(),
      idle({ waiting: 1, current: 'new.pdf', step: 'read', total_in_batch: 1, done_in_batch: 0 }),
      idle({ total_in_batch: 1, done_in_batch: 1 }),
    ]
    const { calls } = stubApi(() => ({ body: replies[Math.min(calls.length - 1, 2)] }))
    render(<Host />)
    await tick(0)
    expect(calls).toHaveLength(1)
    await tick(10000)
    expect(calls).toHaveLength(2)
    expect(screen.getByText('Reading 1 of 1')).toBeInTheDocument()
    const busyVersion = Number(screen.getByTestId('version').textContent)
    expect(busyVersion).toBeGreaterThan(0)
    await tick(2000)
    expect(calls).toHaveLength(3)
    expect(screen.getByText('Read 1 of 1')).toBeInTheDocument()
    expect(Number(screen.getByTestId('version').textContent)).toBeGreaterThan(busyVersion)
    await tick(10000)
    expect(calls).toHaveLength(4)
  })

  test('new work that finished between two idle looks still refreshes the lists', async () => {
    const replies: ProgressOut[] = [idle(), idle({ total_in_batch: 1, done_in_batch: 1 })]
    const { calls } = stubApi(() => ({ body: replies[Math.min(calls.length - 1, 1)] }))
    render(<Host />)
    await tick(0)
    expect(screen.getByTestId('version')).toHaveTextContent('0')
    await tick(10000)
    expect(screen.getByTestId('version')).toHaveTextContent('1')
    await tick(10000)
    expect(screen.getByTestId('version')).toHaveTextContent('1')
  })

  test('a hidden page does not poll, and reading starts again when it is shown', async () => {
    const { calls } = stubApi(() => ({ body: idle() }))
    const hidden = vi.spyOn(document, 'hidden', 'get')
    hidden.mockReturnValue(false)
    render(<Host />)
    await tick(0)
    expect(calls).toHaveLength(1)
    hidden.mockReturnValue(true)
    act(() => {
      document.dispatchEvent(new Event('visibilitychange'))
    })
    await tick(60000)
    expect(calls).toHaveLength(1)
    hidden.mockReturnValue(false)
    act(() => {
      document.dispatchEvent(new Event('visibilitychange'))
    })
    await tick(0)
    expect(calls).toHaveLength(2)
    await tick(10000)
    expect(calls).toHaveLength(3)
    hidden.mockRestore()
  })

  test('shows nothing when no batch has run, and no moving parts', async () => {
    stubApi(() => ({ body: idle() }))
    const { container } = render(<Host />)
    await tick(0)
    expect(container.querySelector('progress')).toBeNull()
  })

  test('a bar with words: the value, the maximum and what is being read', async () => {
    stubApi(() => ({
      body: idle({
        waiting: 4,
        current: 'a.pdf',
        step: 'read',
        total_in_batch: 5,
        done_in_batch: 1,
      }),
    }))
    render(<Host />)
    await tick(0)
    const bar = screen.getByRole('progressbar', { name: 'Reading 2 of 5' })
    expect(bar).toHaveAttribute('max', '5')
    expect(bar).toHaveAttribute('value', '1')
    expect(screen.getByText('a.pdf')).toBeInTheDocument()
  })

  test('says how many need a look when the batch is done', async () => {
    stubApi(() => ({ body: idle({ total_in_batch: 5, done_in_batch: 5, asked_in_batch: 2 }) }))
    render(<Host />)
    await tick(0)
    expect(screen.getByText('Read 5 of 5. 2 need a look.')).toBeInTheDocument()
  })

  test('a failed read tries again after 2, 4, 8 and then at most 30 seconds', async () => {
    const { calls } = stubApi(() => ({ status: 500, body: { detail: 'down' } }))
    render(<Host />)
    await tick(0)
    expect(calls).toHaveLength(1)
    await tick(1999)
    expect(calls).toHaveLength(1)
    await tick(1)
    expect(calls).toHaveLength(2)
    await tick(4000)
    expect(calls).toHaveLength(3)
    await tick(8000)
    expect(calls).toHaveLength(4)
    await tick(16000)
    expect(calls).toHaveLength(5)
    await tick(29999)
    expect(calls).toHaveLength(5)
    await tick(1)
    expect(calls).toHaveLength(6)
  })

  test('the retries stop being slow once a read works again', async () => {
    let down = true
    const { calls } = stubApi(() => (down ? { status: 500, body: {} } : { body: idle() }))
    render(<Host />)
    await tick(0)
    down = false
    await tick(2000)
    expect(calls).toHaveLength(2)
    await tick(10000)
    expect(calls).toHaveLength(3)
  })
})

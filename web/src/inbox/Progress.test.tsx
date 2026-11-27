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
  test('progress polls while work is queued and stops when idle', async () => {
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
    await tick(20000)
    expect(calls).toHaveLength(3)
    expect(screen.getByText('Read 3 of 3')).toBeInTheDocument()
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
})

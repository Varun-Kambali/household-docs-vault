import { act, renderHook, waitFor } from '@testing-library/react'
import { describe, expect, test, vi } from 'vitest'

import { useInboxCount } from './useInboxCount.ts'

function answerWith(counts: number[]): void {
  const queue = [...counts]
  vi.stubGlobal(
    'fetch',
    vi.fn(() => {
      const n = queue.shift() ?? 0
      return Promise.resolve(
        new Response(JSON.stringify(Array.from({ length: n }, (_, id) => ({ id }))), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
      )
    }),
  )
}

describe('useInboxCount', () => {
  test('reads once, and again only when asked to refresh', async () => {
    answerWith([2, 1])
    const { result } = renderHook(() => useInboxCount())
    await waitFor(() => expect(result.current.count).toBe(2))
    expect(fetch).toHaveBeenCalledTimes(1)
    act(() => result.current.refresh())
    await waitFor(() => expect(result.current.count).toBe(1))
    expect(fetch).toHaveBeenCalledTimes(2)
  })
})

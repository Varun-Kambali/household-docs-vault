import { act, renderHook, waitFor } from '@testing-library/react'
import { describe, expect, test } from 'vitest'

import { activityEntry, stubApi } from '../test/api.ts'
import { useActivity } from './useActivity.ts'

describe('useActivity', () => {
  test('asking for older entries before any are shown reads nothing', () => {
    const { calls } = stubApi(() => 'hang')
    const { result } = renderHook(() => useActivity(0))
    act(() => result.current.more())
    expect(calls).toHaveLength(1)
  })

  test('a read that is dropped by a newer one is not an error', () => {
    stubApi(() => 'hang')
    const { result, rerender, unmount } = renderHook(({ v }) => useActivity(v), {
      initialProps: { v: 0 },
    })
    rerender({ v: 1 })
    unmount()
    expect(result.current.error).toBeNull()
  })

  test('older pages the new head no longer reaches are dropped', async () => {
    const entries = (from: number, to: number) =>
      Array.from({ length: to - from + 1 }, (_, i) => activityEntry({ id: to - i }))
    let head = entries(81, 100)
    stubApi((call) => (call.path.includes('before=') ? { body: entries(61, 80) } : { body: head }))
    const { result, rerender } = renderHook(({ v }) => useActivity(v), { initialProps: { v: 0 } })
    await waitFor(() => expect(result.current.entries).toHaveLength(20))
    act(() => result.current.more())
    await waitFor(() => expect(result.current.entries).toHaveLength(40))
    // 30 more arrive while busy: the head now starts at 111, with a gap down to the old page.
    head = entries(111, 130)
    rerender({ v: 1 })
    await waitFor(() => expect(result.current.entries?.[0]?.id).toBe(130))
    expect(result.current.entries).toHaveLength(20)
    expect(result.current.hasMore).toBe(true)
  })

  test('older pages are kept when the new head still reaches them', async () => {
    const entries = (from: number, to: number) =>
      Array.from({ length: to - from + 1 }, (_, i) => activityEntry({ id: to - i }))
    let head = entries(81, 100)
    stubApi((call) => (call.path.includes('before=') ? { body: entries(61, 80) } : { body: head }))
    const { result, rerender } = renderHook(({ v }) => useActivity(v), { initialProps: { v: 0 } })
    await waitFor(() => expect(result.current.entries).toHaveLength(20))
    act(() => result.current.more())
    await waitFor(() => expect(result.current.entries).toHaveLength(40))
    head = entries(85, 104)
    rerender({ v: 1 })
    await waitFor(() => expect(result.current.entries?.[0]?.id).toBe(104))
    expect(result.current.entries).toHaveLength(44)
  })
})

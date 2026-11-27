import { act, renderHook } from '@testing-library/react'
import { describe, expect, test } from 'vitest'

import { stubApi } from '../test/api.ts'
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
})

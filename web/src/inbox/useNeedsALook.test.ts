import { renderHook, waitFor } from '@testing-library/react'
import { describe, expect, test } from 'vitest'

import { stubApi, waitingItem } from '../test/api.ts'
import { useNeedsALook } from './useNeedsALook.ts'

describe('useNeedsALook', () => {
  test('keeps the files it had when a later read is refused, and says why', async () => {
    let reads = 0
    stubApi(() =>
      ++reads === 1
        ? { body: [waitingItem()] }
        : { status: 500, body: { detail: 'Something went wrong. Nothing was changed.' } },
    )
    const { result, rerender } = renderHook(({ v }) => useNeedsALook(v), {
      initialProps: { v: 0 },
    })
    await waitFor(() => expect(result.current.items).toHaveLength(1))
    rerender({ v: 1 })
    await waitFor(() => expect(result.current.error).toMatch(/Something went wrong/))
    expect(result.current.items).toHaveLength(1)
  })

  test('a read that is dropped by a newer one is not an error', async () => {
    stubApi(() => 'hang')
    const { result, unmount, rerender } = renderHook(({ v }) => useNeedsALook(v), {
      initialProps: { v: 0 },
    })
    rerender({ v: 1 })
    unmount()
    expect(result.current.error).toBeNull()
  })
})

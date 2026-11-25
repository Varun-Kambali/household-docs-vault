// How many files wait for an answer, for the number beside Inbox in the sidebar. It comes from
// the list the Inbox screen shows (GET /v1/needs-a-look), so the two cannot disagree. Null until
// it is known, and null again if the list cannot be read: no number is better than a wrong one.
import { useEffect, useState } from 'react'

import { api, isAbort } from '../api/client.ts'

export function useInboxCount(refreshKey: string): number | null {
  const [count, setCount] = useState<number | null>(null)
  // refreshKey is not read inside: a new one asks again, so the number follows the person around.
  useEffect(() => {
    const controller = new AbortController()
    api<unknown[]>('/v1/needs-a-look', { signal: controller.signal })
      .then((items) => setCount(items.length))
      .catch((error: unknown) => {
        if (!isAbort(error)) setCount(null)
      })
    return () => controller.abort()
    // oxlint-disable-next-line react/exhaustive-effect-dependencies
  }, [refreshKey])
  return count
}

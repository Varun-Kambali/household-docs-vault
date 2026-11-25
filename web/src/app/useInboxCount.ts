// How many files wait for an answer, for the number beside Inbox in the sidebar. It comes from
// the list the Inbox screen shows (GET /v1/needs-a-look), so the two cannot disagree. The count is
// null until it is known, and null again if the list cannot be read: no number is better than a
// wrong one. The error is the sentence the API (or the client) gave, for the Inbox screen to show.
// api() throws only an ApiError or an abort, so what is caught here has a message to show.
import { useEffect, useState } from 'react'

import { api, isAbort } from '../api/client.ts'

export type Waiting = { count: number | null; error: string | null }

export function useInboxCount(refreshKey: string): Waiting {
  const [waiting, setWaiting] = useState<Waiting>({ count: null, error: null })
  // refreshKey is not read inside: a new one asks again, so the number follows the person around.
  useEffect(() => {
    const controller = new AbortController()
    api<unknown[]>('/v1/needs-a-look', { signal: controller.signal })
      .then((items) => setWaiting({ count: items.length, error: null }))
      .catch((error: unknown) => {
        if (isAbort(error)) return
        setWaiting({
          count: null,
          error: (error as Error).message,
        })
      })
    return () => controller.abort()
    // oxlint-disable-next-line react/exhaustive-effect-dependencies
  }, [refreshKey])
  return waiting
}

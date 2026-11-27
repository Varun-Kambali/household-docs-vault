// The batch the worker is on, read from /v1/inbox/progress. It is read again every 2 seconds while
// work is queued or being read, and every 10 seconds when the worker is idle, so a file dropped
// after the page loaded is noticed. A hidden page does not read at all; coming back to the window
// or calling poke() reads at once. `version` goes up each time the reading changed hands while
// work was going on (and once more when it stopped, or when an idle look finds something new), so
// the lists below can read themselves again.
import { useCallback, useEffect, useRef, useState } from 'react'

import { api, isAbort } from '../api/client.ts'
import type { ProgressOut } from '../api/types.ts'

export const POLL_MS = 2000
export const IDLE_POLL_MS = 10000
export const RETRY_MS = 2000
export const RETRY_MAX_MS = 30000

const busy = (p: ProgressOut): boolean => p.waiting > 0 || p.current !== null

export function useProgress(): {
  progress: ProgressOut | null
  version: number
  poke: () => void
} {
  const [progress, setProgress] = useState<ProgressOut | null>(null)
  const [version, setVersion] = useState(0)
  const [round, setRound] = useState(0)
  const wasBusy = useRef(false)
  const lastSeen = useRef<string | null>(null)
  const poke = useCallback(() => setRound((n) => n + 1), [])

  useEffect(() => {
    const controller = new AbortController()
    let timer: ReturnType<typeof setTimeout> | undefined
    let failures = 0
    function read(): void {
      api<ProgressOut>('/v1/inbox/progress', { signal: controller.signal })
        .then((next) => {
          failures = 0
          setProgress(next)
          const seen = JSON.stringify(next)
          const changed = lastSeen.current !== null && lastSeen.current !== seen
          lastSeen.current = seen
          if (busy(next) || wasBusy.current || changed) setVersion((n) => n + 1)
          wasBusy.current = busy(next)
          if (!document.hidden) timer = setTimeout(read, busy(next) ? POLL_MS : IDLE_POLL_MS)
        })
        .catch((error: unknown) => {
          if (isAbort(error)) return
          // The bar is a courtesy, but a restart of the app must not leave it frozen: try again
          // after 2, 4, 8 seconds and so on, never waiting more than 30.
          wasBusy.current = false
          failures += 1
          if (!document.hidden) {
            timer = setTimeout(read, Math.min(RETRY_MS * 2 ** (failures - 1), RETRY_MAX_MS))
          }
        })
    }
    function onVisibility(): void {
      if (document.hidden) clearTimeout(timer)
      else poke()
    }
    read()
    window.addEventListener('focus', poke)
    document.addEventListener('visibilitychange', onVisibility)
    return () => {
      controller.abort()
      clearTimeout(timer)
      window.removeEventListener('focus', poke)
      document.removeEventListener('visibilitychange', onVisibility)
    }
    // `round` only asks for another read.
    // oxlint-disable-next-line react/exhaustive-effect-dependencies
  }, [round, poke])

  return { progress, version, poke }
}

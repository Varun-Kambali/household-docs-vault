// The list on a screen. Where it comes from depends on the screen: a prompt the model has already
// read (the seed), or a query held in the address (a linked or reloaded list, an area page), which
// is fetched from /v1/search/list with no model call. Changing a part posts the change with the
// query on screen and replaces the rows and the sentence with the answer, then writes the new
// query to the address. Changes made one after another are sent in turn, each on the one before,
// so a second pick never undoes the first. The old rows stay on screen while one is on its way.
import { useCallback, useEffect, useRef, useState } from 'react'

import { api, isAbort } from '../api/client.ts'
import type { ListOut, PartChange } from '../api/types.ts'
import { type ListQuery, fromQuery, listFromParams, listKey, toQueryIn } from './listQuery.ts'

type Held = { key: string; out: ListOut }
type Failure = { key: string; text: string }

export type ListState = {
  view: ListOut | null
  loading: boolean
  error: string | null
  changeError: string | null
  updating: boolean
  change: (part: PartChange) => void
}

export function useList({
  source,
  scope,
  seed,
  onApplied,
}: {
  // The query the address (or the area) names; null when the list comes from a prompt.
  source: ListQuery | null
  // Names what the screen is asked for (the prompt, or the list's key); a new one means the user
  // has gone somewhere else, and changes still on their way are dropped.
  scope: string
  seed: ListOut | null
  onApplied: (query: ListQuery) => void
}): ListState {
  const key = source === null ? null : listKey(source)
  const [held, setHeld] = useState<Held | null>(null)
  const [failure, setFailure] = useState<Failure | null>(null)
  const [changeError, setChangeError] = useState<string | null>(null)
  const [pending, setPending] = useState(0)
  const epoch = useRef(0)
  const own = useRef<string | null>(null)
  const latest = useRef<ListQuery | null>(null)
  const queue = useRef(new Map<string, PartChange>())
  const running = useRef(false)
  const applied = useRef(onApplied)
  useEffect(() => {
    applied.current = onApplied
  })

  // Going somewhere else (not just the address following our own change) drops what is queued.
  useEffect(() => {
    if (own.current !== scope) {
      epoch.current += 1
      queue.current.clear()
      setChangeError(null)
    }
  }, [scope])

  useEffect(() => {
    if (key === null || held?.key === key) return
    // The query is read back from its key, which says it exactly (listQuery.test.ts), so the
    // effect follows the key and not a new object on every render.
    const query = listFromParams(new URLSearchParams(key))
    if (query === null) return
    const controller = new AbortController()
    api<ListOut>('/v1/search/list', {
      method: 'POST',
      body: JSON.stringify({ query: toQueryIn(query) }),
      signal: controller.signal,
    })
      .then((out) => {
        setFailure(null)
        setHeld({ key, out })
      })
      .catch((error: unknown) => {
        if (isAbort(error)) return
        setFailure({ key, text: (error as Error).message })
      })
    return () => controller.abort()
  }, [key, held?.key])

  const view = source === null ? seed : held?.key === key ? held.out : null
  useEffect(() => {
    latest.current = view === null ? null : fromQuery(view.query)
  }, [view])

  // The screen going away drops what is still on its way, as going to another list does.
  useEffect(
    () => () => {
      epoch.current += 1
      queue.current.clear()
    },
    [],
  )

  // Changes wait here, at most one for each part (a later pick of the same part replaces the
  // earlier one, which nobody is waiting to see), and are sent one at a time, each on the list
  // the one before it made.
  const drain = useCallback(async () => {
    if (running.current) return
    running.current = true
    try {
      for (;;) {
        const next = queue.current.entries().next()
        if (next.done === true) break
        const [slot, part] = next.value
        queue.current.delete(slot)
        const mine = epoch.current
        if (latest.current === null) continue
        try {
          const out = await api<ListOut>('/v1/search/list', {
            method: 'POST',
            body: JSON.stringify({ query: toQueryIn(latest.current), change: part }),
          })
          if (mine !== epoch.current) continue
          const query = fromQuery(out.query)
          latest.current = query
          own.current = listKey(query)
          setHeld({ key: own.current, out })
          applied.current(query)
        } catch (error) {
          if (mine === epoch.current) setChangeError((error as Error).message)
        }
        setPending(queue.current.size + 1)
      }
    } finally {
      running.current = false
      setPending(0)
    }
  }, [])

  const change = useCallback(
    (part: PartChange) => {
      queue.current.delete(part.slot)
      queue.current.set(part.slot, part)
      setChangeError(null)
      setPending(queue.current.size + (running.current ? 1 : 0))
      void drain()
    },
    [drain],
  )

  return {
    view,
    loading: source !== null && view === null && failure?.key !== key,
    error: source !== null && failure?.key === key ? failure.text : null,
    changeError,
    updating: pending > 0,
    change,
  }
}

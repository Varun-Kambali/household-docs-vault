// The search as you type. The quick search (no model) runs 150 ms after the last key and the full
// one (the model reads the prompt) 600 ms after it, or at once from `runFull`. A new key aborts
// whatever is still on its way, so an old answer can never replace a newer one. Every result is
// remembered with the prompt it answers, so a screen never shows a full answer for another prompt.
import { useCallback, useEffect, useRef, useState } from 'react'

import { api, isAbort } from '../api/client.ts'
import type { PartChange, SearchOut } from '../api/types.ts'

export const QUICK_MS = 150
export const FULL_MS = 600

type Held = {
  // The latest quick result is kept while the next one is on its way, so the list does not flash.
  quick: SearchOut | null
  full: { prompt: string; out: SearchOut } | null
  reading: string | null
  error: { prompt: string; text: string } | null
  fullError: { prompt: string; text: string } | null
}

const EMPTY: Held = { quick: null, full: null, reading: null, error: null, fullError: null }

export type SearchState = {
  quick: SearchOut | null
  full: SearchOut | null
  // The quick search has not answered yet and nothing is shown.
  loading: boolean
  // The full search is on its way (the model is reading).
  reading: boolean
  // A change to the lookup's sentence is on its way.
  changing: boolean
  error: string | null
  fullError: string | null
}

function post(prompt: string, full: boolean, signal: AbortSignal): Promise<SearchOut> {
  return api<SearchOut>('/v1/search', {
    method: 'POST',
    body: JSON.stringify({ prompt, full }),
    signal,
  })
}

export function useSearch(prompt: string): {
  state: SearchState
  runFull: () => void
  reset: () => void
  // One part of a lookup's sentence changed: the lookup runs again on the query the screen holds,
  // with no model reading the prompt a second time.
  change: (part: PartChange) => void
} {
  const text = prompt.trim()
  const [held, setHeld] = useState<Held>(EMPTY)
  const runNow = useRef<(() => void) | null>(null)
  const [changing, setChanging] = useState(false)
  const queue = useRef(new Map<string, PartChange>())
  const draining = useRef(false)
  const current = useRef<{ text: string; out: SearchOut | null }>({ text: '', out: null })
  const epoch = useRef(0)

  useEffect(() => {
    if (text === '') return
    const controller = new AbortController()
    let fullTimer: ReturnType<typeof setTimeout> | undefined
    let fullStarted = false

    const quickTimer = setTimeout(() => {
      post(text, false, controller.signal)
        .then((quick) => setHeld((now) => ({ ...now, quick, error: null })))
        .catch((error: unknown) => {
          if (isAbort(error)) return
          setHeld((now) => ({
            ...now,
            quick: null,
            error: { prompt: text, text: (error as Error).message },
          }))
        })
    }, QUICK_MS)

    function startFull(): void {
      if (fullStarted) return
      fullStarted = true
      clearTimeout(fullTimer)
      setHeld((now) => ({ ...now, reading: text, fullError: null }))
      post(text, true, controller.signal)
        .then((out) => setHeld((now) => ({ ...now, full: { prompt: text, out }, reading: null })))
        .catch((error: unknown) => {
          if (isAbort(error)) return
          // Enter on the same prompt asks again.
          fullStarted = false
          setHeld((now) => ({
            ...now,
            reading: null,
            fullError: { prompt: text, text: (error as Error).message },
          }))
        })
    }
    fullTimer = setTimeout(startFull, FULL_MS)
    runNow.current = startFull

    return () => {
      controller.abort()
      clearTimeout(quickTimer)
      clearTimeout(fullTimer)
      runNow.current = null
    }
  }, [text])

  const reset = useCallback(() => setHeld(EMPTY), [])

  // A new prompt drops changes still waiting for the old one.
  useEffect(() => {
    epoch.current += 1
    queue.current.clear()
  }, [text])

  // Changes are sent one at a time, each on the query the one before it made, so a second pick
  // never undoes the first; a later pick of the same part replaces an earlier one still waiting.
  const drain = useCallback(async () => {
    if (draining.current) return
    draining.current = true
    setChanging(true)
    try {
      for (;;) {
        const next = queue.current.entries().next()
        if (next.done === true) break
        const [slot, part] = next.value
        queue.current.delete(slot)
        const { text: asked, out } = current.current
        const mine = epoch.current
        if (out?.query == null) continue
        try {
          const result = await api<SearchOut>('/v1/search', {
            method: 'POST',
            body: JSON.stringify({ prompt: asked, full: true, query: out.query, change: part }),
          })
          if (mine !== epoch.current) continue
          setHeld((now) => ({ ...now, full: { prompt: asked, out: result }, fullError: null }))
        } catch (error) {
          if (mine === epoch.current) {
            setHeld((now) => ({
              ...now,
              fullError: { prompt: asked, text: (error as Error).message },
            }))
          }
        }
      }
    } finally {
      draining.current = false
      setChanging(false)
    }
  }, [])

  const change = useCallback(
    (part: PartChange) => {
      queue.current.delete(part.slot)
      queue.current.set(part.slot, part)
      void drain()
    },
    [drain],
  )

  const idle = text === ''
  const full = !idle && held.full?.prompt === text ? held.full.out : null
  useEffect(() => {
    current.current = { text, out: full }
  })
  const error = !idle && held.error?.prompt === text ? held.error.text : null
  const state: SearchState = {
    quick: idle ? null : held.quick,
    full,
    loading: !idle && held.quick === null && full === null && error === null,
    reading: !idle && held.reading === text,
    changing,
    error,
    fullError: !idle && held.fullError?.prompt === text ? held.fullError.text : null,
  }
  return { state, runFull: () => runNow.current?.(), reset, change }
}

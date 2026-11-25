// The search as you type. The quick search (no model) runs 150 ms after the last key and the full
// one (the model reads the prompt) 600 ms after it, or at once from `runFull`. A new key aborts
// whatever is still on its way, so an old answer can never replace a newer one. Every result is
// remembered with the prompt it answers, so a screen never shows a full answer for another prompt.
import { useCallback, useEffect, useRef, useState } from 'react'

import { api, isAbort } from '../api/client.ts'
import type { SearchOut } from '../api/types.ts'

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
} {
  const text = prompt.trim()
  const [held, setHeld] = useState<Held>(EMPTY)
  const runNow = useRef<(() => void) | null>(null)

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
      setHeld((now) => ({ ...now, reading: text }))
      post(text, true, controller.signal)
        .then((out) => setHeld((now) => ({ ...now, full: { prompt: text, out }, reading: null })))
        .catch((error: unknown) => {
          if (isAbort(error)) return
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

  const idle = text === ''
  const full = !idle && held.full?.prompt === text ? held.full.out : null
  const error = !idle && held.error?.prompt === text ? held.error.text : null
  const state: SearchState = {
    quick: idle ? null : held.quick,
    full,
    loading: !idle && held.quick === null && full === null && error === null,
    reading: !idle && held.reading === text,
    error,
    fullError: !idle && held.fullError?.prompt === text ? held.fullError.text : null,
  }
  return { state, runFull: () => runNow.current?.(), reset }
}

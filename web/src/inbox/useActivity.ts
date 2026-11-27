// The activity log, newest first. The first page is read again when `version` changes; older pages
// are added by more(), each from the oldest entry shown, and are kept across a re-read.
import { useCallback, useEffect, useState } from 'react'

import { api, isAbort } from '../api/client.ts'
import type { ActivityOut } from '../api/types.ts'

export const PAGE = 20

export type ActivityState = {
  entries: ActivityOut[] | null
  error: string | null
  hasMore: boolean
  more: () => void
}

type Held = {
  head: ActivityOut[] | null
  // Older pages, kept across a re-read of the head while the head still reaches them.
  older: ActivityOut[]
  // Whether the last older page came back full; null until one has been read.
  olderFull: boolean | null
}

const NONE: Held = { head: null, older: [], olderFull: null }

// What a re-read of the head does to what is held. The entries the old head showed that the new
// head no longer does join the older ones; but if more than a page arrived meanwhile, nothing
// ties the new head to the old ones, and showing them would hide the entries in between, so they
// are dropped and "Show older" starts again from the head.
function merged(held: Held, page: ActivityOut[]): Held {
  if (held.head === null) return { ...NONE, head: page }
  const least = minId(page)
  const joined = page.length < PAGE || maxId(held.head) >= least - 1
  if (!joined) return { head: page, older: [], olderFull: null }
  const pool = [...held.head, ...held.older].filter((e) => e.id < least)
  return { head: page, older: pool, olderFull: held.olderFull }
}

export function useActivity(version: number): ActivityState {
  const [held, setHeld] = useState<Held>(NONE)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const controller = new AbortController()
    api<ActivityOut[]>(`/v1/activity?limit=${PAGE}`, { signal: controller.signal })
      .then((page) => {
        setHeld((now) => merged(now, page))
        setError(null)
      })
      .catch((reason: unknown) => {
        if (!isAbort(reason)) setError((reason as Error).message)
      })
    return () => controller.abort()
    // `version` only asks for another read.
    // oxlint-disable-next-line react/exhaustive-effect-dependencies
  }, [version])

  const { head, older, olderFull } = held
  const entries = head === null ? null : [...head, ...older]
  const oldest = entries?.at(-1)?.id

  const loadMore = useCallback(() => {
    if (oldest === undefined) return
    api<ActivityOut[]>(`/v1/activity?limit=${PAGE}&before=${oldest}`)
      .then((page) =>
        setHeld((now) => ({
          ...now,
          older: [...now.older, ...page],
          olderFull: page.length === PAGE,
        })),
      )
      .catch((reason: unknown) => setError((reason as Error).message))
  }, [oldest])

  return {
    entries,
    error,
    hasMore: olderFull ?? head?.length === PAGE,
    more: loadMore,
  }
}

function maxId(entries: ActivityOut[]): number {
  return entries.reduce((most, e) => Math.max(most, e.id), Number.NEGATIVE_INFINITY)
}

function minId(entries: ActivityOut[]): number {
  return entries.reduce((least, e) => Math.min(least, e.id), Number.POSITIVE_INFINITY)
}

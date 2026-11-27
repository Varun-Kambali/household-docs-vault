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

export function useActivity(version: number): ActivityState {
  const [head, setHead] = useState<ActivityOut[] | null>(null)
  const [older, setOlder] = useState<ActivityOut[]>([])
  // Whether the last older page came back full; null until one has been read.
  const [olderFull, setOlderFull] = useState<boolean | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const controller = new AbortController()
    api<ActivityOut[]>(`/v1/activity?limit=${PAGE}`, { signal: controller.signal })
      .then((page) => {
        setHead(page)
        setError(null)
      })
      .catch((reason: unknown) => {
        if (!isAbort(reason)) setError((reason as Error).message)
      })
    return () => controller.abort()
    // `version` only asks for another read.
    // oxlint-disable-next-line react/exhaustive-effect-dependencies
  }, [version])

  const entries = head === null ? null : [...head, ...older.filter((e) => e.id < minId(head))]
  const oldest = entries?.at(-1)?.id

  const loadMore = useCallback(() => {
    if (oldest === undefined) return
    api<ActivityOut[]>(`/v1/activity?limit=${PAGE}&before=${oldest}`)
      .then((page) => {
        setOlder((have) => [...have, ...page])
        setOlderFull(page.length === PAGE)
      })
      .catch((reason: unknown) => setError((reason as Error).message))
  }, [oldest])

  return {
    entries,
    error,
    hasMore: olderFull ?? head?.length === PAGE,
    more: loadMore,
  }
}

function minId(entries: ActivityOut[]): number {
  return entries.reduce((least, e) => Math.min(least, e.id), Number.POSITIVE_INFINITY)
}

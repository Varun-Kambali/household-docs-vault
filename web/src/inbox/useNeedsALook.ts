// The files waiting for an answer, from /v1/needs-a-look. Read again whenever `version` changes.
import { useEffect, useState } from 'react'

import { api, isAbort } from '../api/client.ts'
import type { NeedsALookOut } from '../api/types.ts'

export function useNeedsALook(version: number): {
  items: NeedsALookOut[] | null
  error: string | null
} {
  const [read, setRead] = useState<{ items: NeedsALookOut[] | null; error: string | null }>({
    items: null,
    error: null,
  })
  useEffect(() => {
    const controller = new AbortController()
    api<NeedsALookOut[]>('/v1/needs-a-look', { signal: controller.signal })
      .then((items) => setRead({ items, error: null }))
      .catch((reason: unknown) => {
        if (!isAbort(reason)) setRead((was) => ({ ...was, error: (reason as Error).message }))
      })
    return () => controller.abort()
    // `version` only asks for another read.
    // oxlint-disable-next-line react/exhaustive-effect-dependencies
  }, [version])
  return read
}

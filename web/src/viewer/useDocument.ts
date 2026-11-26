// One document's stored record (its pages, fields and where it is filed), with the sentence the
// API gave when it cannot be read.
import { useEffect, useState } from 'react'

import { api, isAbort } from '../api/client.ts'
import type { DocumentOut } from '../api/types.ts'

export type Loaded =
  { state: 'loading' } | { state: 'error'; error: string } | { state: 'full'; doc: DocumentOut }

export function useDocument(id: string): Loaded {
  const [read, setRead] = useState<{ id: string; result: Loaded } | null>(null)
  useEffect(() => {
    const controller = new AbortController()
    api<DocumentOut>(`/v1/documents/${encodeURIComponent(id)}`, { signal: controller.signal })
      .then((doc) => setRead({ id, result: { state: 'full', doc } }))
      .catch((error: unknown) => {
        if (!isAbort(error)) {
          setRead({ id, result: { state: 'error', error: (error as Error).message } })
        }
      })
    return () => controller.abort()
  }, [id])
  return read !== null && read.id === id ? read.result : { state: 'loading' }
}

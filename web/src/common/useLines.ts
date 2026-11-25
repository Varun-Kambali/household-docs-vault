// The stored text of the lines on one page, so an outline can be named by what it outlines.
import { useEffect, useState } from 'react'

import { api } from '../api/client.ts'
import type { PageLinesOut } from '../api/types.ts'

export type PageLines = { texts: ReadonlyMap<number, string>; boxes: PageLinesOut['lines'] }

const NONE: PageLines = { texts: new Map(), boxes: [] }

export function useLines(documentId: string | null, page: number): PageLines {
  const key = `${documentId ?? ''}/${page}`
  // What was read, and for which page; another page's lines are never shown for this one.
  const [read, setRead] = useState<{ key: string; lines: PageLines } | null>(null)
  useEffect(() => {
    if (documentId === null) return
    const controller = new AbortController()
    api<PageLinesOut>(`/v1/documents/${encodeURIComponent(documentId)}/pages/${page}/lines`, {
      signal: controller.signal,
    })
      .then((reply) =>
        setRead({
          key,
          lines: {
            texts: new Map(reply.lines.map((line) => [line.idx, line.text])),
            boxes: reply.lines,
          },
        }),
      )
      // Without the text an outline is still there, named by its number.
      .catch(() => undefined)
    return () => controller.abort()
  }, [documentId, page, key])
  return read !== null && read.key === key ? read.lines : NONE
}

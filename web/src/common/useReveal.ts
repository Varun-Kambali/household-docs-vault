// Show in folder. On the Mac it opens the folder; anywhere else (or when Finder cannot be reached)
// the API answers 409 and the Drive path is copied for the owner to look up.
import { useCallback, useState } from 'react'

import { ApiError, api } from '../api/client.ts'

export type RevealState =
  { kind: 'idle' } | { kind: 'ok'; text: string } | { kind: 'error'; text: string }

export function useReveal(): {
  state: RevealState
  reveal: (id: string, drivePath: string) => void
} {
  const [state, setState] = useState<RevealState>({ kind: 'idle' })
  const reveal = useCallback((id: string, drivePath: string) => {
    api<void>(`/v1/documents/${encodeURIComponent(id)}/reveal`, { method: 'POST' })
      .then(() => setState({ kind: 'ok', text: 'Opened the folder.' }))
      .catch(async (error: unknown) => {
        if (error instanceof ApiError && error.status === 409) {
          try {
            await navigator.clipboard.writeText(drivePath)
            setState({ kind: 'ok', text: 'Drive path copied' })
          } catch {
            setState({ kind: 'error', text: `Copy this Drive path yourself: ${drivePath}` })
          }
          return
        }
        setState({ kind: 'error', text: (error as Error).message })
      })
  }, [])
  return { state, reveal }
}

// A file never disappears from the list without a line saying where it went. After an answer the
// line says "Filing <file>", then (read from the activity log) "Filed in <folders>" with Undo for
// ten seconds, or that it was discarded. Cmd+Z does the Undo of the last filing.
import { useEffect, useState } from 'react'

import { api, isAbort } from '../api/client.ts'
import type { ActivityOut } from '../api/types.ts'
import { stepLabel, whereFiled } from './steps.ts'

export type Pending = { id: number; name: string; at: number }

const SHOWN_MS = 10_000
const GIVE_UP_MS = 180_000 // the log still has it, and a file asked again is in the list above
const SKEW_MS = 5000

type Note =
  | { kind: 'filing' }
  | { kind: 'filed'; where: string | null; documentId: string | null }
  | { kind: 'ended'; text: string }
  | { kind: 'again' }

function noteFor(pending: Pending, entries: ActivityOut[]): Note {
  const mine = entries
    .filter((e) => e.item_id === pending.id && Date.parse(e.time) >= pending.at - SKEW_MS)
    .sort((a, b) => b.id - a.id)[0]
  if (mine === undefined) return { kind: 'filing' }
  if (mine.step === 'filed')
    return { kind: 'filed', where: whereFiled(mine.file), documentId: mine.document_id ?? null }
  if (mine.step === 'needs_a_look') return { kind: 'again' }
  if (['discarded', 'gone', 'error', 'kept_both'].includes(mine.step)) {
    return { kind: 'ended', text: `${stepLabel(mine.step)} ${pending.name}` }
  }
  return { kind: 'filing' }
}

export function FilingNotice({
  pending,
  version,
  onChanged,
  onDone,
}: {
  pending: Pending[]
  version: number
  onChanged: () => void
  onDone: (id: number) => void
}) {
  const [entries, setEntries] = useState<ActivityOut[]>([])
  const [refusal, setRefusal] = useState<string | null>(null)
  const count = pending.length

  useEffect(() => {
    if (count === 0) return
    const controller = new AbortController()
    api<ActivityOut[]>('/v1/activity?limit=50', { signal: controller.signal })
      .then(setEntries)
      .catch((reason: unknown) => {
        if (!isAbort(reason)) setRefusal((reason as Error).message)
      })
    return () => controller.abort()
    // `version` only asks for another read.
    // oxlint-disable-next-line react/exhaustive-effect-dependencies
  }, [count, version])

  const notes = pending.map((p) => ({ p, note: noteFor(p, entries) }))

  async function undo(p: Pending, documentId: string): Promise<void> {
    setRefusal(null)
    try {
      await api(`/v1/documents/${documentId}/undo`, { method: 'POST' })
      onChanged()
      onDone(p.id)
    } catch (reason) {
      setRefusal((reason as Error).message)
    }
  }

  const last = [...notes].reverse().find((n) => n.note.kind === 'filed')
  useEffect(() => {
    function onKey(event: KeyboardEvent): void {
      if (!(event.metaKey || event.ctrlKey) || event.key.toLowerCase() !== 'z') return
      if (event.target instanceof HTMLInputElement || event.target instanceof HTMLTextAreaElement)
        return
      if (last === undefined || last.note.kind !== 'filed' || last.note.documentId === null) return
      event.preventDefault()
      void undo(last.p, last.note.documentId)
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  })

  // The slot stays when nothing is pending, so a notice appearing moves nothing under the pointer.
  return (
    <div className="notices">
      {refusal !== null && (
        <p className="region-error" role="alert">
          {refusal}
        </p>
      )}
      {notes.map(({ p, note }) => (
        <Line key={p.id} pending={p} note={note} onDone={onDone} onUndo={undo} />
      ))}
    </div>
  )
}

function Line({
  pending,
  note,
  onDone,
  onUndo,
}: {
  pending: Pending
  note: Note
  onDone: (id: number) => void
  onUndo: (p: Pending, documentId: string) => Promise<void>
}) {
  const kind = note.kind
  useEffect(() => {
    if (kind === 'again') return onDone(pending.id)
    const wait = kind === 'filing' ? GIVE_UP_MS : SHOWN_MS
    const timer = setTimeout(() => onDone(pending.id), wait)
    return () => clearTimeout(timer)
  }, [kind, pending.id, onDone])

  if (note.kind === 'again') return null
  return (
    <output className="notice">
      {note.kind === 'filed' && (
        <svg
          aria-hidden="true"
          width="16"
          height="16"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.5"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <path d="M20 6 9 17l-5-5" />
        </svg>
      )}
      <span>
        {note.kind === 'filing' && `Filing ${pending.name}`}
        {note.kind === 'filed' &&
          (note.where === null ? `Filed ${pending.name}` : `Filed in ${note.where}`)}
        {note.kind === 'ended' && note.text}
      </span>
      {note.kind === 'filed' && note.documentId !== null && (
        <button
          type="button"
          className="link-button"
          onClick={() => void onUndo(pending, note.documentId ?? '')}
        >
          Undo
        </button>
      )}
    </output>
  )
}

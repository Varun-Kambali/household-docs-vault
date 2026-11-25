// The Search screen: the box, the quick finder under it, and (when the full search lands) the
// answer beside its page. Results are a function of the prompt, which lives in the address.
import { useEffect, useRef, useState, type KeyboardEvent } from 'react'

import type { RowOut } from '../api/types.ts'
import { navigate } from '../app/location.ts'
import { hrefFor } from '../app/route.ts'
import { Region } from '../app/Region.tsx'
import { usePeople } from '../common/usePeople.ts'
import { useReveal } from '../common/useReveal.ts'
import { AnswerPanel } from './AnswerPanel.tsx'
import { Finder } from './Finder.tsx'
import { FINDER_ID, optionId } from './finderIds.ts'
import { NoAnswer } from './NoAnswer.tsx'
import { openRow } from './openAt.ts'
import { useSearch } from './useSearch.ts'

export const MODEL_OFF =
  "Reading prompts needs the local model, which isn't running. Showing keyword matches."

export function SearchPage({ q, focusTick }: { q: string; focusTick: number }) {
  const box = useRef<HTMLInputElement>(null)
  const people = usePeople()
  const { state, runFull, reset } = useSearch(q)
  const { state: revealed, reveal } = useReveal()
  // The active row belongs to the list it was chosen in; a new list starts with none.
  const [cursor, setCursor] = useState<{ list: unknown; index: number }>({ list: null, index: -1 })

  // On opening, and whenever / or Cmd+K is pressed on this screen.
  useEffect(() => {
    box.current?.focus()
    // oxlint-disable-next-line react/exhaustive-effect-dependencies
  }, [focusTick])

  const shown = state.full ?? state.quick
  const answer = state.full?.answer ?? null
  const none = state.full?.no_answer ?? null
  const closest = none !== null ? new Set(none.closest) : null
  const all = shown?.rows ?? []
  const rows =
    closest !== null && all.some((r) => closest.has(r.rel_path))
      ? all.filter((r) => closest.has(r.rel_path))
      : all
  const prompt = q.trim()
  const off = shown?.reading === 'off'
  const active = cursor.list === shown ? cursor.index : -1

  function open(row: RowOut): void {
    navigate(openRow(row))
  }

  function onKeyDown(event: KeyboardEvent<HTMLInputElement>): void {
    const last = rows.length - 1
    if (event.key === 'Escape' && q !== '') {
      reset()
      navigate('/', { replace: true })
    } else if (event.key === 'ArrowDown' && rows.length > 0) {
      event.preventDefault()
      setCursor({ list: shown, index: Math.min(active + 1, last) })
    } else if (event.key === 'ArrowUp' && rows.length > 0) {
      event.preventDefault()
      setCursor({ list: shown, index: Math.max(active - 1, 0) })
    } else if (event.key === 'Enter') {
      event.preventDefault()
      const row = rows[active]
      if (event.metaKey || event.ctrlKey) {
        const target = row ?? rows[0]
        if (target !== undefined) reveal(target.document_id, target.drive_path)
      } else if (row !== undefined) open(row)
      else if (prompt !== '') runFull()
    }
  }

  const rowOf = (id: string): RowOut | undefined => all.find((r) => r.document_id === id)
  const list =
    state.error !== null
      ? 'error'
      : prompt === ''
        ? 'idle'
        : shown === null
          ? 'loading'
          : rows.length === 0
            ? 'empty'
            : 'full'

  return (
    <>
      <h1 tabIndex={-1}>Search</h1>
      <input
        ref={box}
        className="prompt"
        type="search"
        name="q"
        autoComplete="off"
        aria-label="Ask about your documents"
        aria-controls={rows.length > 0 ? FINDER_ID : undefined}
        aria-activedescendant={active >= 0 && active < rows.length ? optionId(active) : undefined}
        placeholder="Kavita's health policy"
        value={q}
        onChange={(event) => {
          if (event.target.value.trim() === '') reset()
          navigate(hrefFor({ name: 'search', q: event.target.value }), { replace: true })
        }}
        onKeyDown={onKeyDown}
      />
      {off && <p className="hint model-off">{MODEL_OFF}</p>}
      {list === 'idle' && (
        <p className="hint">Ask in a few words. Name a person, a kind of document or a date.</p>
      )}
      {state.fullError !== null && (
        <p className="region-error" role="alert">
          {state.fullError}
        </p>
      )}
      {state.reading && <output className="region-note">Reading your question</output>}
      {answer !== null && (
        <AnswerPanel
          key={`${answer.document_id}-${answer.field}-${answer.text}`}
          answer={answer}
          row={rowOf(answer.document_id)}
          onReveal={(row) => reveal(row.document_id, row.drive_path)}
        />
      )}
      {none !== null && (
        <NoAnswer
          reason={none.reason}
          unread={state.full?.query?.unread ?? []}
          hasRows={rows.length > 0}
        />
      )}
      {list !== 'idle' && (
        <Region
          state={
            list === 'error'
              ? 'error'
              : list === 'loading'
                ? 'loading'
                : list === 'empty'
                  ? 'empty'
                  : 'full'
          }
          what="matching files"
          empty="No file matches that."
          error={state.error ?? undefined}
        >
          <Finder rows={rows} prompt={prompt} people={people} active={active} onOpen={open} />
        </Region>
      )}
      {revealed.kind !== 'idle' &&
        (revealed.kind === 'ok' ? (
          <output className="reveal-note">{revealed.text}</output>
        ) : (
          <p className="region-error" role="alert">
            {revealed.text}
          </p>
        ))}
    </>
  )
}

// What the app did, newest first: the time, the step, the sentence and the file. The newest entry
// of a file carries what can be done with it now (the actions the API lists for it).
import { useState } from 'react'

import { api } from '../api/client.ts'
import type { ActivityOut } from '../api/types.ts'
import { navigate } from '../app/location.ts'
import { Region } from '../app/Region.tsx'
import { hrefFor } from '../app/route.ts'
import { dayKey, formatClock, formatDay, stepLabel } from './steps.ts'
import { useActivity } from './useActivity.ts'

const ANSWERS = ['answer', 'unlock', 'discard', 'keep_both']

export function Activity({
  version,
  onChanged,
  onShow,
}: {
  version: number
  onChanged: () => void
  // Show a file that still waits for an answer in the list above.
  onShow: (itemId: number) => void
}) {
  const { entries, error, hasMore, more } = useActivity(version)
  const [refusal, setRefusal] = useState<string | null>(null)

  async function post(path: string): Promise<void> {
    setRefusal(null)
    try {
      await api(path, { method: 'POST' })
      onChanged()
    } catch (reason) {
      setRefusal((reason as Error).message)
    }
  }

  const state =
    error !== null && entries === null
      ? 'error'
      : entries === null
        ? 'loading'
        : entries.length === 0
          ? 'empty'
          : 'full'

  return (
    <section aria-labelledby="activity-title" className="inbox-section">
      <h2 id="activity-title">Activity</h2>
      {(refusal ?? (entries !== null ? error : null)) !== null && (
        <p className="region-error" role="alert">
          {refusal ?? error}
        </p>
      )}
      <Region
        state={state}
        what="the activity"
        empty="Nothing has happened yet."
        error={error ?? undefined}
      >
        {byDay(entries ?? []).map(({ key, day, items }) => (
          <div key={key} className="activity-day">
            <h3 id={`activity-${key}`}>{day}</h3>
            <ul className="activity" aria-labelledby={`activity-${key}`}>
              {items.map((entry) => (
                <Row key={entry.id} entry={entry} post={post} onShow={onShow} />
              ))}
            </ul>
          </div>
        ))}
        {hasMore && (
          <p className="actions">
            <button type="button" className="button" onClick={more}>
              Show older
            </button>
          </p>
        )}
      </Region>
    </section>
  )
}

// Newest first, as the log is; a new heading starts where the day changes.
function byDay(entries: ActivityOut[]): { key: string; day: string; items: ActivityOut[] }[] {
  const groups: { key: string; day: string; items: ActivityOut[] }[] = []
  for (const entry of entries) {
    const key = dayKey(entry.time)
    const last = groups.at(-1)
    if (last?.key === key) last.items.push(entry)
    else groups.push({ key, day: formatDay(entry.time), items: [entry] })
  }
  return groups
}

function Row({
  entry,
  post,
  onShow,
}: {
  entry: ActivityOut
  post: (path: string) => Promise<void>
  onShow: (itemId: number) => void
}) {
  const { actions, item_id: itemId, document_id: documentId } = entry
  const open = actions.includes('open') && itemId !== null
  const doc = documentId ?? null
  return (
    <li className="activity-row">
      <time className="activity-time" dateTime={entry.time}>
        {formatClock(entry.time)}
      </time>
      <span className="activity-step">{stepLabel(entry.step)}</span>
      <span className="activity-detail">
        {entry.step !== 'needs_a_look' && entry.detail}
        {entry.file !== null && <span className="activity-file hint">{entry.file}</span>}
      </span>
      <span className="activity-actions">
        {open &&
          (doc !== null ? (
            <a
              className="link-button"
              href={hrefFor({ name: 'doc', id: doc, page: 0, lines: null })}
              onClick={(event) => {
                if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey) return
                event.preventDefault()
                navigate(hrefFor({ name: 'doc', id: doc, page: 0, lines: null }))
              }}
            >
              Open
            </a>
          ) : (
            <button type="button" className="link-button" onClick={() => onShow(itemId)}>
              Open
            </button>
          ))}
        {itemId !== null && actions.some((a) => ANSWERS.includes(a)) && (
          <button type="button" className="link-button" onClick={() => onShow(itemId)}>
            Answer
          </button>
        )}
        {itemId !== null &&
          actions.includes('undo') &&
          (entry.step === 'filed' || doc !== null) && (
            <button
              type="button"
              className="link-button"
              onClick={() =>
                void post(
                  doc !== null ? `/v1/documents/${doc}/undo` : `/v1/needs-a-look/${itemId}/undo`,
                )
              }
            >
              Undo
            </button>
          )}
        {itemId !== null && actions.includes('retry') && (
          <button
            type="button"
            className="link-button"
            onClick={() => void post(`/v1/items/${itemId}/retry`)}
          >
            Retry
          </button>
        )}
      </span>
    </li>
  )
}

// The files the filer could not settle, one at a time. Left: the first page of the file on the
// grey canvas. Right: the question and its answers. Other waiting files that ask the very same
// question can be answered together. Where it goes after an answer is for the screen to say, so
// this tells it which files were answered.
import { Fragment, useEffect, useRef, useState } from 'react'

import { api, ApiError } from '../api/client.ts'
import type { NeedsALookOut } from '../api/types.ts'
import { Question, type Answer, type Seen } from './Question.tsx'
import { UnlockDialog } from './UnlockDialog.tsx'

export type Focus = { id: number; n: number }

const sameQuestion = (a: NeedsALookOut, b: NeedsALookOut): boolean =>
  a.question.answer_kind === b.question.answer_kind && a.question.text === b.question.text

function Page({ item }: { item: NeedsALookOut }) {
  const [failed, setFailed] = useState(false)
  return (
    <div className="inbox-page">
      {failed ? (
        <p className="region-empty">
          {item.question.answer_kind === 'unlock'
            ? 'This PDF is locked. Its pages show once you enter the password.'
            : 'This page cannot be shown.'}
        </p>
      ) : (
        <img
          src={`/v1/items/${item.id}/pages/0.png?width=900`}
          alt={`First page of ${item.name}`}
          onError={() => setFailed(true)}
        />
      )}
    </div>
  )
}

// A 409 from answer-many that says which files it queued and which it refused, as the sentence
// to show and the files that are being filed.
function partlyAnswered(
  reason: unknown,
  items: NeedsALookOut[],
): { answered: Seen[]; message: string } | null {
  if (!(reason instanceof ApiError)) return null
  const { answered, refused } = reason.body
  if (!Array.isArray(answered) || typeof refused !== 'object' || refused === null) return null
  const name = (id: number): string => items.find((i) => i.id === id)?.name ?? 'a file'
  const queued = answered
    .filter((id): id is number => typeof id === 'number')
    .map((id) => ({ id, name: name(id) }))
  const left = Object.entries(refused).map(([id, why]) => `${name(Number(id))} (${String(why)})`)
  return { answered: queued, message: `Not answered: ${left.join(', ')}.` }
}

export function NeedsALook({
  items,
  focus,
  onChanged,
  onAnswered,
}: {
  items: NeedsALookOut[]
  // Show this file now (Open in the activity list); `n` makes the same file ask again.
  focus: Focus | null
  onChanged: () => void
  onAnswered: (seen: Seen[]) => void
}) {
  const [currentId, setCurrentId] = useState<number | null>(null)
  const [lastFocus, setLastFocus] = useState<Focus | null>(null)
  const [chosen, setChosen] = useState<ReadonlySet<number>>(new Set())
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [unlocking, setUnlocking] = useState(false)
  const wantFocus = useRef(false)
  const answeredIds = useRef<ReadonlySet<number>>(new Set())
  const rootRef = useRef<HTMLDivElement>(null)
  const emptyRef = useRef<HTMLParagraphElement>(null)

  if (focus !== lastFocus) {
    setLastFocus(focus)
    if (focus !== null) setCurrentId(focus.id)
  }

  const item = items.find((i) => i.id === currentId) ?? items[0]
  const itemId = item?.id
  const itemCount = items.length

  // An action that removes the button it was started from leaves the focus nowhere. It goes to
  // the next file's question, or to the empty sentence, as soon as one of them is on screen.
  useEffect(() => {
    if (!wantFocus.current) return
    if (itemCount === 0) {
      wantFocus.current = false
      emptyRef.current?.focus()
    } else if (itemId !== undefined && !answeredIds.current.has(itemId)) {
      wantFocus.current = false
      rootRef.current?.querySelector<HTMLElement>('.question h2')?.focus()
    }
  })

  if (item === undefined) {
    return (
      <p className="region-empty" tabIndex={-1} ref={emptyRef}>
        Nothing waiting. New files are read as they arrive.
      </p>
    )
  }
  const others =
    item.question.answer_kind === 'person'
      ? items.filter((i) => i.id !== item.id && sameQuestion(i, item))
      : []
  const ticked = others.filter((o) => chosen.has(o.id))

  function nextAfter(answered: number[]): number | null {
    const rest = items.filter((i) => !answered.includes(i.id))
    const at = rest.findIndex((i) => i.id > (item?.id ?? 0))
    return (rest[at === -1 ? 0 : at] ?? rest[0])?.id ?? null
  }

  function refocus(answered: number[]): void {
    answeredIds.current = new Set(answered)
    wantFocus.current = true
  }

  function move(): void {
    const at = items.findIndex((i) => i.id === item?.id)
    setCurrentId(items[(at + 1) % items.length]?.id ?? null)
    setError(null)
    refocus([])
  }

  function afterAnswer(answered: Seen[]): void {
    refocus(answered.map((a) => a.id))
    setCurrentId(nextAfter(answered.map((a) => a.id)))
    setChosen(new Set())
    onAnswered(answered)
  }

  async function send(path: string, body: unknown, answered: Seen[]): Promise<void> {
    setBusy(true)
    setError(null)
    try {
      await api(path, { method: 'POST', body: JSON.stringify(body) })
      afterAnswer(answered)
    } catch (reason) {
      // Some of several files may have been queued before the rest were refused: those are being
      // filed, and the rest are named. The list is read again either way, as it may have moved.
      const partly = partlyAnswered(reason, items)
      if (partly !== null) {
        afterAnswer(partly.answered)
        setError(partly.message)
      } else {
        setError((reason as Error).message)
      }
    } finally {
      setBusy(false)
      onChanged()
    }
  }

  const here: Seen = { id: item.id, name: item.name }
  return (
    <div className="inbox-item" ref={rootRef}>
      <Fragment key={item.id}>
        <Page item={item} />
        <Question
          item={item}
          others={others.map((o) => ({ id: o.id, name: o.name }))}
          chosen={chosen}
          onToggle={(id) =>
            setChosen((have) => {
              const next = new Set(have)
              if (!next.delete(id)) next.add(id)
              return next
            })
          }
          busy={busy}
          error={error}
          onAnswer={(answer: Answer) =>
            void send(`/v1/needs-a-look/${item.id}/answer`, answer, [here])
          }
          onAnswerMany={(value) =>
            void send(
              '/v1/needs-a-look/answer-many',
              { item_ids: [item.id, ...ticked.map((o) => o.id)], value },
              [here, ...ticked.map((o) => ({ id: o.id, name: o.name }))],
            )
          }
          onUnlock={() => setUnlocking(true)}
          onSkip={items.length > 1 ? move : null}
        />
      </Fragment>
      <UnlockDialog
        open={unlocking}
        item={here}
        onClose={() => setUnlocking(false)}
        onDone={(unlocked) => {
          setUnlocking(false)
          refocus([unlocked.id])
          onAnswered([unlocked])
          onChanged()
        }}
      />
    </div>
  )
}

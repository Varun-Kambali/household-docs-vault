// The files the filer could not settle, one at a time. Left: the first page of the file on the
// grey canvas. Right: the question and its answers. Other waiting files that ask the very same
// question can be answered together. Where it goes after an answer is for the screen to say, so
// this tells it which files were answered.
import { Fragment, useState } from 'react'

import { api } from '../api/client.ts'
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
        <p className="region-empty">This page cannot be shown.</p>
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

  if (focus !== lastFocus) {
    setLastFocus(focus)
    if (focus !== null) setCurrentId(focus.id)
  }

  const item = items.find((i) => i.id === currentId) ?? items[0]
  if (item === undefined) {
    return <p className="region-empty">Nothing waiting. New files are read as they arrive.</p>
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

  function move(): void {
    const at = items.findIndex((i) => i.id === item?.id)
    setCurrentId(items[(at + 1) % items.length]?.id ?? null)
    setError(null)
  }

  async function send(path: string, body: unknown, answered: Seen[]): Promise<void> {
    setBusy(true)
    setError(null)
    try {
      await api(path, { method: 'POST', body: JSON.stringify(body) })
      setCurrentId(nextAfter(answered.map((a) => a.id)))
      setChosen(new Set())
      onAnswered(answered)
      onChanged()
    } catch (reason) {
      setError((reason as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const here: Seen = { id: item.id, name: item.name }
  return (
    <div className="inbox-item">
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
        onDone={() => {
          setUnlocking(false)
          onAnswered([here])
          onChanged()
        }}
      />
    </div>
  )
}

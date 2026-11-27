// The Inbox: the one question the filer could not settle comes first, then the activity log. The
// batch bar reads itself while work is going on, and the lists read themselves again each time it
// does. Cards and the secrets file are the two buttons under the title.
import { useCallback, useState } from 'react'

import { Region } from '../app/Region.tsx'
import { Activity } from './Activity.tsx'
import { CardUpload } from './CardUpload.tsx'
import { FilingNotice, type Pending } from './FilingNotice.tsx'
import { NeedsALook, type Focus } from './NeedsALook.tsx'
import { Progress } from './Progress.tsx'
import { SecretsDialog } from './SecretsDialog.tsx'
import { useNeedsALook } from './useNeedsALook.ts'
import { useProgress } from './useProgress.ts'

export function InboxPage({ onChanged }: { onChanged: () => void }) {
  const { progress, version: worked, poke } = useProgress()
  const [mine, setMine] = useState(0)
  const version = worked + mine
  const { items, error } = useNeedsALook(version)
  const [pending, setPending] = useState<Pending[]>([])
  const [focus, setFocus] = useState<Focus | null>(null)
  const [dialog, setDialog] = useState<'card' | 'secrets' | null>(null)

  const changed = useCallback(() => {
    setMine((n) => n + 1)
    poke()
    onChanged()
  }, [poke, onChanged])
  const done = useCallback(
    (id: number) => setPending((have) => have.filter((p) => p.id !== id)),
    [],
  )
  const close = useCallback(() => setDialog(null), [])

  const state = error !== null && items === null ? 'error' : items === null ? 'loading' : 'full'

  return (
    <>
      <h1 tabIndex={-1}>Inbox</h1>
      <Progress progress={progress} />
      <div className="actions inbox-tools">
        <button type="button" className="button" onClick={() => setDialog('card')}>
          Upload a card
        </button>
        <button type="button" className="button" onClick={() => setDialog('secrets')}>
          Secrets file
        </button>
        <FilingNotice pending={pending} version={version} onChanged={changed} onDone={done} />
      </div>
      <section aria-labelledby="needs-title" className="inbox-section">
        <h2 id="needs-title" tabIndex={-1}>
          Needs a look
        </h2>
        {error !== null && items !== null && (
          <p className="region-error" role="alert">
            {error}
          </p>
        )}
        <Region state={state} what="the Inbox" error={error ?? undefined}>
          <NeedsALook
            items={items ?? []}
            focus={focus}
            onChanged={changed}
            onAnswered={(seen) =>
              setPending((have) => [
                ...have.filter((p) => !seen.some((s) => s.id === p.id)),
                ...seen.map((s) => ({ ...s, at: Date.now() })),
              ])
            }
          />
        </Region>
      </section>
      <Activity
        version={version}
        onChanged={changed}
        onShow={(id) => {
          setFocus((was) => ({ id, n: (was?.n ?? 0) + 1 }))
          document.getElementById('needs-title')?.focus()
        }}
      />
      <CardUpload open={dialog === 'card'} onClose={close} onDone={changed} />
      <SecretsDialog open={dialog === 'secrets'} onClose={close} onDone={changed} />
    </>
  )
}

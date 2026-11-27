// Upload a card: the front photo, an optional back photo and the master password, posted as the
// form the API takes. The reply says only filed or waiting: the number and the CVV go to
// Secrets.kdbx and never come back to a screen. The password is emptied as it is sent.
import { useId, useState, type FormEvent } from 'react'

import { api } from '../api/client.ts'
import type { CardOut } from '../api/types.ts'
import { Dialog } from '../common/Dialog.tsx'
import { PasswordField } from './PasswordField.tsx'

export function CardUpload({
  open,
  onClose,
  onDone,
}: {
  open: boolean
  onClose: () => void
  onDone: () => void
}) {
  return (
    <Dialog open={open} title="Upload a card" onClose={onClose}>
      <CardForm onClose={onClose} onDone={onDone} />
    </Dialog>
  )
}

function CardForm({ onClose, onDone }: { onClose: () => void; onDone: () => void }) {
  const [front, setFront] = useState<File | null>(null)
  const [back, setBack] = useState<File | null>(null)
  const [master, setMaster] = useState('')
  const [problem, setProblem] = useState<string | null>(null)
  const [result, setResult] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  // Changing the key empties the two file boxes, which a page cannot do any other way.
  const [round, setRound] = useState(0)
  const frontId = useId()
  const backId = useId()

  async function submit(event: FormEvent): Promise<void> {
    event.preventDefault()
    if (front === null) return setProblem('Choose the front of the card.')
    if (master === '') return setProblem('Type the master password.')
    const form = new FormData()
    form.append('front', front)
    if (back !== null) form.append('back', back)
    form.append('master_password', master)
    setBusy(true)
    setProblem(null)
    setMaster('')
    try {
      const card = await api<CardOut>('/v1/cards', { method: 'POST', body: form })
      setResult(
        card.status === 'filed'
          ? 'Filed. The card number is kept in Secrets.kdbx.'
          : 'Waiting. The card needs an answer in the list on this page, or a clearer photo.',
      )
      setFront(null)
      setBack(null)
      setRound((n) => n + 1)
      onDone()
    } catch (reason) {
      setProblem((reason as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <form onSubmit={(event) => void submit(event)} className="dialog-form">
      <p>The photos are read on this Mac. The number and the security code are never shown here.</p>
      <div className="field-row" key={round}>
        <label htmlFor={frontId}>Front of the card</label>
        <input
          id={frontId}
          className="file-input"
          type="file"
          accept="image/jpeg,image/png,image/heic"
          onChange={(event) => setFront(event.target.files?.[0] ?? null)}
        />
      </div>
      <div className="field-row" key={`back-${round}`}>
        <label htmlFor={backId}>Back of the card (optional)</label>
        <input
          id={backId}
          className="file-input"
          type="file"
          accept="image/jpeg,image/png,image/heic"
          onChange={(event) => setBack(event.target.files?.[0] ?? null)}
        />
      </div>
      <PasswordField label="Master password" value={master} onChange={setMaster} />
      {problem !== null && (
        <p className="region-error" role="alert">
          {problem}
        </p>
      )}
      {result !== null && <output className="dialog-result">{result}</output>}
      <div className="actions">
        <button type="submit" className="button button-primary" disabled={busy}>
          Upload the card
        </button>
        <button type="button" className="button" onClick={onClose}>
          {result === null ? 'Cancel' : 'Done'}
        </button>
      </div>
    </form>
  )
}

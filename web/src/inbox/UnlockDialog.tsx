// Unlock a locked PDF with its password, and (if asked) keep the password in Secrets.kdbx, which
// needs the master password. Both live in this form's state for the one submit and are emptied as
// soon as it is sent, whether it worked or not. They go in the request body only, never in an
// address, and the form is gone when the dialog closes.
import { useId, useState, type FormEvent } from 'react'

import { api } from '../api/client.ts'
import { Dialog } from '../common/Dialog.tsx'
import { PasswordField } from './PasswordField.tsx'

type Item = { id: number; name: string }

export function UnlockDialog({
  open,
  item,
  onClose,
  onDone,
}: {
  open: boolean
  item: Item
  onClose: () => void
  onDone: (item: Item) => void
}) {
  // The file the dialog was opened for stays the target while it is open, even if the list under
  // it is read again and another file comes first.
  const [opened, setOpened] = useState<Item | null>(null)
  if (open && opened === null) setOpened(item)
  if (!open && opened !== null) setOpened(null)
  return (
    <Dialog open={open} title="Unlock this PDF" onClose={onClose}>
      <UnlockForm item={opened ?? item} onClose={onClose} onDone={onDone} />
    </Dialog>
  )
}

function UnlockForm({
  item,
  onClose,
  onDone,
}: {
  item: Item
  onClose: () => void
  onDone: (item: Item) => void
}) {
  const [password, setPassword] = useState('')
  const [save, setSave] = useState(false)
  const [master, setMaster] = useState('')
  const [problem, setProblem] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const saveId = useId()

  async function submit(event: FormEvent): Promise<void> {
    event.preventDefault()
    if (password === '') return setProblem('Type the password of the PDF.')
    if (save && master === '') return setProblem('Type the master password to save it.')
    const body = { password, save, master_password: save ? master : null }
    setBusy(true)
    setProblem(null)
    // Whatever happens next, nothing typed stays in the form.
    setPassword('')
    setMaster('')
    try {
      await api(`/v1/needs-a-look/${item.id}/unlock`, {
        method: 'POST',
        body: JSON.stringify(body),
      })
      onDone(item)
    } catch (reason) {
      setProblem((reason as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <form onSubmit={(event) => void submit(event)} className="dialog-form">
      <p>
        Type the password for {item.name}. The app on this Mac reads it once and does not keep it.
      </p>
      <PasswordField label="PDF password" value={password} onChange={setPassword} />
      <label className="check-row" htmlFor={saveId}>
        <input
          id={saveId}
          type="checkbox"
          checked={save}
          onChange={(event) => setSave(event.target.checked)}
        />
        <span>Save it in Secrets.kdbx</span>
      </label>
      {save && <PasswordField label="Master password" value={master} onChange={setMaster} />}
      {problem !== null && (
        <p className="region-error" role="alert">
          {problem}
        </p>
      )}
      <div className="actions">
        <button type="submit" className="button button-primary" disabled={busy}>
          Open the PDF
        </button>
        <button type="button" className="button" onClick={onClose}>
          Cancel
        </button>
      </div>
    </form>
  )
}

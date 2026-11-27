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
  onDone: () => void
}) {
  return (
    <Dialog open={open} title="Unlock this PDF" onClose={onClose}>
      <UnlockForm item={item} onClose={onClose} onDone={onDone} />
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
  onDone: () => void
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
      onDone()
    } catch (reason) {
      setProblem((reason as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <form onSubmit={(event) => void submit(event)} className="dialog-form">
      <p>The password for {item.name}. It is sent to the app on this Mac and is not kept.</p>
      <PasswordField label="PDF password" value={password} onChange={setPassword} />
      <div className="check-row">
        <input
          id={saveId}
          type="checkbox"
          checked={save}
          onChange={(event) => setSave(event.target.checked)}
        />
        <label htmlFor={saveId}>Save it in Secrets.kdbx</label>
      </div>
      {save && <PasswordField label="Master password" value={master} onChange={setMaster} />}
      {problem !== null && (
        <p className="region-error" role="alert">
          {problem}
        </p>
      )}
      <div className="actions">
        <button type="submit" className="button button-primary" disabled={busy}>
          Unlock
        </button>
        <button type="button" className="button" onClick={onClose}>
          Cancel
        </button>
      </div>
    </form>
  )
}

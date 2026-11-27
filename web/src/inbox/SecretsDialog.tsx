// Make Secrets.kdbx (the master password, typed twice) or open it (typed once). It reads
// /v1/secrets/status when it opens. The master password is held for the one submit and emptied as
// it is sent; nothing about it is kept between openings.
import { useEffect, useState, type FormEvent } from 'react'

import { api, isAbort } from '../api/client.ts'
import type { SecretsStatusOut } from '../api/types.ts'
import { Dialog } from '../common/Dialog.tsx'
import { Region } from '../app/Region.tsx'
import { PasswordField } from './PasswordField.tsx'

export function SecretsDialog({
  open,
  onClose,
  onDone,
}: {
  open: boolean
  onClose: () => void
  onDone: () => void
}) {
  return (
    <Dialog open={open} title="Secrets file" onClose={onClose}>
      <SecretsForm onClose={onClose} onDone={onDone} />
    </Dialog>
  )
}

type Read = { status: SecretsStatusOut | null; error: string | null }

function SecretsForm({ onClose, onDone }: { onClose: () => void; onDone: () => void }) {
  const [read, setRead] = useState<Read>({ status: null, error: null })
  const [done, setDone] = useState<string | null>(null)
  const [master, setMaster] = useState('')
  const [again, setAgain] = useState('')
  const [problem, setProblem] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    const controller = new AbortController()
    api<SecretsStatusOut>('/v1/secrets/status', { signal: controller.signal })
      .then((status) => setRead({ status, error: null }))
      .catch((reason: unknown) => {
        if (!isAbort(reason)) setRead({ status: null, error: (reason as Error).message })
      })
    return () => controller.abort()
  }, [])

  const status = read.status
  const making = status !== null && !status.exists

  async function submit(event: FormEvent): Promise<void> {
    event.preventDefault()
    if (master === '') return setProblem('Type the master password.')
    if (making && master !== again) return setProblem('The two passwords are not the same.')
    const body = JSON.stringify({ master_password: master })
    setBusy(true)
    setProblem(null)
    setMaster('')
    setAgain('')
    try {
      await api(making ? '/v1/secrets/create' : '/v1/secrets/unlock', { method: 'POST', body })
      setDone(making ? 'Secrets.kdbx is made and open.' : 'Secrets.kdbx is open.')
      onDone()
    } catch (reason) {
      setProblem((reason as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const state = read.error !== null ? 'error' : status === null ? 'loading' : 'full'
  return (
    <Region state={state} what="the secrets file" error={read.error ?? undefined}>
      {done !== null || status?.unlocked === true ? (
        <>
          <output className="dialog-result">
            {done ?? 'Secrets.kdbx is open. It locks itself after 10 minutes.'}
          </output>
          <div className="actions">
            <button type="button" className="button button-primary" onClick={onClose}>
              Done
            </button>
          </div>
        </>
      ) : (
        <form onSubmit={(event) => void submit(event)} className="dialog-form">
          <p>
            {making
              ? 'Card numbers are kept in a file only this password opens. There is no way to get the password back, so keep it somewhere safe.'
              : 'Type the master password to open Secrets.kdbx for 10 minutes.'}
          </p>
          <PasswordField label="Master password" value={master} onChange={setMaster} />
          {making && <PasswordField label="Type it again" value={again} onChange={setAgain} />}
          {problem !== null && (
            <p className="region-error" role="alert">
              {problem}
            </p>
          )}
          <div className="actions">
            <button type="submit" className="button button-primary" disabled={busy}>
              {making ? 'Create Secrets.kdbx' : 'Unlock Secrets.kdbx'}
            </button>
            <button type="button" className="button" onClick={onClose}>
              Cancel
            </button>
          </div>
        </form>
      )}
    </Region>
  )
}

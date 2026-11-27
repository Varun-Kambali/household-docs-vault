import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, test, vi } from 'vitest'

import { stubApi } from '../test/api.ts'
import { UnlockDialog } from './UnlockDialog.tsx'

// Made up for this test: not a real password, and not the vault's.
const PDF_PW = 'test-only-pdf-pw'
const MASTER_PW = 'test-only-master-pw'

function open(onDone = vi.fn<() => void>(), onClose = vi.fn<() => void>()) {
  render(
    <UnlockDialog
      open
      item={{ id: 3, name: 'policy-locked.pdf' }}
      onClose={onClose}
      onDone={onDone}
    />,
  )
  return { onDone, onClose }
}

describe('UnlockDialog', () => {
  test('asks for the password in a masked field that the browser is told not to remember', () => {
    stubApi(() => undefined)
    open()
    const field = screen.getByLabelText('PDF password')
    expect(field).toHaveAttribute('type', 'password')
    expect(field).toHaveAttribute('autocomplete', 'off')
    expect(screen.getByText(/policy-locked\.pdf/)).toBeInTheDocument()
    expect(screen.queryByLabelText('Master password')).not.toBeInTheDocument()
  })

  test('the unlock password is cleared after submit and never sent in a URL', async () => {
    const { calls } = stubApi(() => ({
      status: 409,
      body: { detail: 'That password did not open the PDF' },
    }))
    const user = userEvent.setup()
    open()
    await user.type(screen.getByLabelText('PDF password'), PDF_PW)
    await user.click(screen.getByRole('button', { name: 'Open the PDF' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'That password did not open the PDF',
    )
    expect(screen.getByLabelText('PDF password')).toHaveValue('')
    expect(calls).toHaveLength(1)
    expect(calls[0]?.method).toBe('POST')
    expect(calls[0]?.path).toBe('/v1/needs-a-look/3/unlock')
    expect(calls[0]?.body).toEqual({ password: PDF_PW, save: false, master_password: null })
    expect(JSON.stringify(calls.map((c) => c.path))).not.toContain(PDF_PW)
    expect(window.location.href).not.toContain(PDF_PW)
    expect(document.body.textContent).not.toContain(PDF_PW)
  })

  test('saving it in Secrets.kdbx asks for the master password, and clears both', async () => {
    const { calls } = stubApi(() => ({ body: { id: 3, state: 'queued' } }))
    const user = userEvent.setup()
    const { onDone } = open()
    await user.type(screen.getByLabelText('PDF password'), PDF_PW)
    await user.click(screen.getByRole('checkbox', { name: 'Save it in Secrets.kdbx' }))
    const master = screen.getByLabelText('Master password')
    expect(master).toHaveAttribute('type', 'password')
    expect(master).toHaveAttribute('autocomplete', 'off')
    await user.type(master, MASTER_PW)
    await user.click(screen.getByRole('button', { name: 'Open the PDF' }))
    expect(calls[0]?.body).toEqual({ password: PDF_PW, save: true, master_password: MASTER_PW })
    expect(onDone).toHaveBeenCalledTimes(1)
  })

  test('does not send an empty password', async () => {
    const { calls } = stubApi(() => undefined)
    const user = userEvent.setup()
    open()
    await user.click(screen.getByRole('button', { name: 'Open the PDF' }))
    expect(calls).toHaveLength(0)
    expect(screen.getByRole('alert')).toHaveTextContent('Type the password of the PDF.')
  })

  test('saving without a master password is turned away before anything is sent', async () => {
    const { calls } = stubApi(() => undefined)
    const user = userEvent.setup()
    open()
    await user.type(screen.getByLabelText('PDF password'), PDF_PW)
    await user.click(screen.getByRole('checkbox', { name: 'Save it in Secrets.kdbx' }))
    await user.click(screen.getByRole('button', { name: 'Open the PDF' }))
    expect(calls).toHaveLength(0)
    expect(screen.getByRole('alert')).toHaveTextContent('Type the master password to save it.')
    expect(screen.getByLabelText('PDF password')).toHaveValue(PDF_PW)
  })

  test('Cancel closes without sending', async () => {
    const { calls } = stubApi(() => undefined)
    const user = userEvent.setup()
    const { onClose } = open()
    await user.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(onClose).toHaveBeenCalled()
    expect(calls).toHaveLength(0)
  })
})

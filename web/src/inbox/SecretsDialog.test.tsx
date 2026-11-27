import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, test, vi } from 'vitest'

import { stubApi, type Call, type Reply } from '../test/api.ts'
import { SecretsDialog } from './SecretsDialog.tsx'

// Made up for this test: not a real password.
const MASTER_PW = 'test-only-master-pw'

function status(exists: boolean, unlocked: boolean) {
  return (call: Call): Reply | undefined =>
    call.path === '/v1/secrets/status' ? { body: { exists, unlocked } } : undefined
}

function show(onDone = vi.fn<() => void>()) {
  render(<SecretsDialog open onClose={vi.fn<() => void>()} onDone={onDone} />)
  return { onDone }
}

describe('SecretsDialog', () => {
  test('with no file, asks for the master password twice and creates it', async () => {
    const { calls } = stubApi((call) =>
      call.method === 'POST' ? { body: { status: 'created' } } : status(false, false)(call),
    )
    const user = userEvent.setup()
    const { onDone } = show()
    const first = await screen.findByLabelText('Master password')
    expect(first).toHaveAttribute('type', 'password')
    expect(first).toHaveAttribute('autocomplete', 'off')
    expect(screen.getByLabelText('Type it again')).toHaveAttribute('type', 'password')
    await user.type(first, MASTER_PW)
    await user.type(screen.getByLabelText('Type it again'), MASTER_PW)
    await user.click(screen.getByRole('button', { name: 'Create Secrets.kdbx' }))
    const post = calls.find((c) => c.method === 'POST')
    expect(post?.path).toBe('/v1/secrets/create')
    expect(post?.body).toEqual({ master_password: MASTER_PW })
    expect(await screen.findByText('Secrets.kdbx is made and open.')).toBeInTheDocument()
    expect(onDone).toHaveBeenCalled()
    expect(JSON.stringify(calls.map((c) => c.path))).not.toContain(MASTER_PW)
  })

  test('focus goes to the master password field once the status is read', async () => {
    stubApi(status(true, false))
    show()
    const field = await screen.findByLabelText('Master password')
    await waitFor(() => expect(field).toHaveFocus())
  })

  test('two different passwords are turned away before anything is sent', async () => {
    const { calls } = stubApi(status(false, false))
    const user = userEvent.setup()
    show()
    await user.type(await screen.findByLabelText('Master password'), MASTER_PW)
    await user.type(screen.getByLabelText('Type it again'), 'something-else')
    await user.click(screen.getByRole('button', { name: 'Create Secrets.kdbx' }))
    expect(screen.getByRole('alert')).toHaveTextContent('The two passwords are not the same.')
    expect(calls.filter((c) => c.method === 'POST')).toHaveLength(0)
  })

  test('with a locked file, asks once and unlocks; a wrong password is cleared', async () => {
    const { calls } = stubApi((call) =>
      call.method === 'POST'
        ? {
            status: 423,
            body: { detail: 'The secrets file could not be opened. Check the master password.' },
          }
        : status(true, false)(call),
    )
    const user = userEvent.setup()
    show()
    await user.type(await screen.findByLabelText('Master password'), MASTER_PW)
    expect(screen.queryByLabelText('Type it again')).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Unlock Secrets.kdbx' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('could not be opened')
    expect(screen.getByLabelText('Master password')).toHaveValue('')
    expect(calls.find((c) => c.method === 'POST')?.path).toBe('/v1/secrets/unlock')
  })

  test('says so when it is already open, with nothing to type', async () => {
    stubApi(status(true, true))
    show()
    expect(await screen.findByText(/is open/)).toBeInTheDocument()
    expect(screen.queryByLabelText('Master password')).not.toBeInTheDocument()
  })

  test('shows the reason when the status cannot be read', async () => {
    stubApi(() => ({ status: 500, body: { detail: 'Something went wrong. Nothing was changed.' } }))
    show()
    expect(await screen.findByRole('alert')).toHaveTextContent('Something went wrong')
  })
})

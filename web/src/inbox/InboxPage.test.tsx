import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, test, vi } from 'vitest'

import type { NeedsALookOut } from '../api/types.ts'
import { activityEntry, idle, lockedItem, stubApi, waitingItem, type Call } from '../test/api.ts'
import { InboxPage } from './InboxPage.tsx'

function server(
  items: NeedsALookOut[],
  extra?: (call: Call) => ReturnType<Parameters<typeof stubApi>[0]>,
) {
  return stubApi((call) => {
    const reply = extra?.(call)
    if (reply !== undefined) return reply
    if (call.path === '/v1/needs-a-look') return { body: items }
    if (call.path.startsWith('/v1/activity')) return { body: [activityEntry({ item_id: 99 })] }
    if (call.path === '/v1/inbox/progress') return { body: idle() }
    if (call.path === '/v1/secrets/status') return { body: { exists: true, unlocked: false } }
    if (call.method === 'POST') return { body: { id: 7, state: 'queued' } }
    return undefined
  })
}

describe('InboxPage', () => {
  test('puts the question first and the activity under it', async () => {
    server([waitingItem()])
    render(<InboxPage onChanged={vi.fn<() => void>()} />)
    expect(await screen.findByRole('heading', { name: /Whose is it\?/ })).toBeInTheDocument()
    expect(await screen.findByText('Filed as Prescription')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Needs a look' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Activity' })).toBeInTheDocument()
  })

  test('says so when nothing is waiting, and still shows the activity', async () => {
    server([])
    render(<InboxPage onChanged={vi.fn<() => void>()} />)
    expect(
      await screen.findByText('Nothing waiting. New files are read as they arrive.'),
    ).toBeInTheDocument()
    expect(await screen.findByText('Filed as Prescription')).toBeInTheDocument()
  })

  test('shows the reason when the list cannot be read', async () => {
    stubApi((call) =>
      call.path === '/v1/needs-a-look'
        ? { status: 500, body: { detail: 'Something went wrong. Nothing was changed.' } }
        : call.path === '/v1/inbox/progress'
          ? { body: idle() }
          : { body: [] },
    )
    render(<InboxPage onChanged={vi.fn<() => void>()} />)
    expect((await screen.findAllByRole('alert'))[0]).toHaveTextContent('Something went wrong')
  })

  test('an answer says it is filing, tells the sidebar and reads the list again', async () => {
    let listed = 0
    const { calls } = server([waitingItem()], (call) =>
      call.path === '/v1/needs-a-look' && ++listed > 1 ? { body: [] } : undefined,
    )
    const onChanged = vi.fn<() => void>()
    const user = userEvent.setup()
    render(<InboxPage onChanged={onChanged} />)
    await user.click(await screen.findByRole('radio', { name: 'Kavita Rao' }))
    await user.click(screen.getByRole('button', { name: 'File it' }))
    expect(await screen.findByText('Filing prescription-1.pdf')).toBeInTheDocument()
    expect(onChanged).toHaveBeenCalled()
    expect(calls.filter((c) => c.path === '/v1/needs-a-look').length).toBeGreaterThan(1)
    expect(
      await screen.findByText('Nothing waiting. New files are read as they arrive.'),
    ).toBeInTheDocument()
  })

  test('Answer in the activity list shows that file in the question', async () => {
    const asked = activityEntry({
      id: 30,
      item_id: 8,
      step: 'needs_a_look',
      actions: ['open', 'undo', 'answer'],
      document_id: null,
      detail: 'Whose is it?',
    })
    const second = waitingItem({
      id: 8,
      name: 'second.pdf',
      question: { ...waitingItem().question, text: 'Another question?' },
    })
    server([waitingItem(), second], (call) =>
      call.path.startsWith('/v1/activity') ? { body: [asked] } : undefined,
    )
    const user = userEvent.setup()
    render(<InboxPage onChanged={vi.fn<() => void>()} />)
    await screen.findByRole('heading', { name: /Whose is it\?/ })
    await user.click(await screen.findByRole('button', { name: 'Answer' }))
    expect(await screen.findByRole('heading', { name: 'Another question?' })).toBeInTheDocument()
  })

  test('the card upload and secrets dialogs open from buttons and give the focus back', async () => {
    server([waitingItem()])
    const user = userEvent.setup()
    render(<InboxPage onChanged={vi.fn<() => void>()} />)
    const card = await screen.findByRole('button', { name: 'Upload a card' })
    await user.click(card)
    expect(screen.getByRole('dialog', { name: 'Upload a card' })).toBeInTheDocument()
    await user.keyboard('{Escape}')
    expect(card).toHaveFocus()
    const secrets = screen.getByRole('button', { name: 'Secrets file' })
    await user.click(secrets)
    const dialog = await screen.findByRole('dialog', { name: 'Secrets file' })
    expect(await within(dialog).findByLabelText('Master password')).toBeInTheDocument()
    await user.keyboard('{Escape}')
    expect(secrets).toHaveFocus()
  })

  test('a locked file offers Unlock and the dialog opens on it', async () => {
    server([lockedItem()])
    const user = userEvent.setup()
    render(<InboxPage onChanged={vi.fn<() => void>()} />)
    await user.click(await screen.findByRole('button', { name: 'Unlock' }))
    expect(screen.getByRole('dialog', { name: 'Unlock this PDF' })).toBeInTheDocument()
  })
})

import { fireEvent, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, test, vi } from 'vitest'

import type { NeedsALookOut } from '../api/types.ts'
import { lockedItem, stubApi, waitingItem } from '../test/api.ts'
import { NeedsALook } from './NeedsALook.tsx'

type Seen = { id: number; name: string }

function show(items: NeedsALookOut[], focusId: number | null = null) {
  const focus = focusId === null ? null : { id: focusId, n: 1 }
  const onChanged = vi.fn<() => void>()
  const onAnswered = vi.fn<(seen: Seen[]) => void>()
  const view = render(
    <NeedsALook items={items} focus={focus} onChanged={onChanged} onAnswered={onAnswered} />,
  )
  return { onChanged, onAnswered, ...view }
}

const SECOND = waitingItem({ id: 8, name: 'prescription-2.pdf', file: 'Needs a look/p2.pdf' })
const THIRD = waitingItem({ id: 9, name: 'prescription-3.pdf', file: 'Needs a look/p3.pdf' })
const OK = { body: { id: 7, state: 'queued' } }

describe('NeedsALook', () => {
  test('shows one file at a time: its page, its question and its answers as radios', () => {
    stubApi(() => OK)
    show([waitingItem(), SECOND])
    expect(
      screen.getByRole('heading', { name: 'Prescription with no name I know on it. Whose is it?' }),
    ).toBeInTheDocument()
    const group = screen.getByRole('radiogroup')
    expect(
      within(group)
        .getAllByRole('radio')
        .map((r) => r.closest('label')?.textContent),
    ).toEqual(['Ravi Kumar Rao', 'Kavita Rao', 'Home'])
    expect(screen.getByRole('img', { name: 'First page of prescription-1.pdf' })).toHaveAttribute(
      'src',
      '/v1/items/7/pages/0.png?width=900',
    )
    expect(screen.getByRole('button', { name: 'File it' })).toBeDisabled()
    expect(screen.queryByRole('img', { name: /prescription-2/ })).not.toBeInTheDocument()
  })

  test('File it sends the chosen answer, then tells the screen which file it was', async () => {
    const { calls } = stubApi(() => OK)
    const user = userEvent.setup()
    const { onChanged, onAnswered } = show([waitingItem()])
    await user.click(screen.getByRole('radio', { name: 'Kavita Rao' }))
    await user.click(screen.getByRole('button', { name: 'File it' }))
    expect(calls[0]).toMatchObject({
      method: 'POST',
      path: '/v1/needs-a-look/7/answer',
      body: { kind: 'person', value: 'p2' },
    })
    expect(onAnswered).toHaveBeenCalledWith([{ id: 7, name: 'prescription-1.pdf' }])
    expect(onChanged).toHaveBeenCalled()
  })

  test('the keys 1 to 9 choose, Enter files and S skips', async () => {
    const { calls } = stubApi(() => OK)
    const user = userEvent.setup()
    show([waitingItem(), SECOND])
    await user.keyboard('2')
    expect(screen.getByRole('radio', { name: 'Kavita Rao' })).toBeChecked()
    await user.keyboard('{Enter}')
    expect(calls[0]?.body).toEqual({ kind: 'person', value: 'p2' })
    // The next file is on screen once the answer is sent; S moves on from there.
    expect(await screen.findByRole('img', { name: /prescription-2\.pdf/ })).toBeInTheDocument()
    await user.keyboard('s')
    expect(screen.getByRole('img', { name: /prescription-1\.pdf/ })).toBeInTheDocument()
  })

  test('Skip for now moves to the next file and round again', async () => {
    stubApi(() => OK)
    const user = userEvent.setup()
    show([waitingItem(), SECOND])
    await user.click(screen.getByRole('button', { name: 'Skip for now' }))
    expect(screen.getByRole('img', { name: /prescription-2\.pdf/ })).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Skip for now' }))
    expect(screen.getByRole('img', { name: /prescription-1\.pdf/ })).toBeInTheDocument()
  })

  test('with one file there is nothing to skip to', () => {
    stubApi(() => OK)
    show([waitingItem()])
    expect(screen.queryByRole('button', { name: 'Skip for now' })).not.toBeInTheDocument()
  })

  test('answering several at once sends answer-many', async () => {
    const { calls } = stubApi(() => ({ body: [{ id: 7, state: 'queued' }] }))
    const user = userEvent.setup()
    const { onAnswered } = show([waitingItem(), SECOND, THIRD])
    expect(screen.getByText('2 more files ask the same thing')).toBeInTheDocument()
    await user.click(screen.getByRole('checkbox', { name: 'prescription-2.pdf' }))
    await user.click(screen.getByRole('checkbox', { name: 'prescription-3.pdf' }))
    await user.click(screen.getByRole('radio', { name: 'Home' }))
    await user.click(screen.getByRole('button', { name: 'Answer all' }))
    expect(calls[0]).toMatchObject({
      path: '/v1/needs-a-look/answer-many',
      body: { item_ids: [7, 8, 9], value: 'home' },
    })
    expect(onAnswered).toHaveBeenCalledWith([
      { id: 7, name: 'prescription-1.pdf' },
      { id: 8, name: 'prescription-2.pdf' },
      { id: 9, name: 'prescription-3.pdf' },
    ])
  })

  test('only files with the same question are offered together', () => {
    stubApi(() => OK)
    const other = waitingItem({
      id: 8,
      question: {
        ...waitingItem().question,
        text: 'Lab report with no name I know on it. Whose is it?',
      },
    })
    show([waitingItem(), other])
    expect(screen.queryByText(/more files? ask the same thing/)).not.toBeInTheDocument()
  })

  test('a partly refused answer-many reports the answered files, re-reads and names the refused', async () => {
    stubApi(() => ({
      status: 409,
      body: {
        detail: '1 of 2 files were not answered',
        answered: [7],
        refused: { '8': 'That file is not in the list any more' },
      },
    }))
    const user = userEvent.setup()
    const { onAnswered, onChanged } = show([waitingItem(), SECOND])
    await user.click(screen.getByRole('checkbox', { name: 'prescription-2.pdf' }))
    await user.click(screen.getByRole('radio', { name: 'Home' }))
    await user.click(screen.getByRole('button', { name: 'Answer all' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Not answered: prescription-2.pdf (That file is not in the list any more).',
    )
    expect(onAnswered).toHaveBeenCalledWith([{ id: 7, name: 'prescription-1.pdf' }])
    expect(onChanged).toHaveBeenCalled()
  })

  test('a refused answer re-reads the list, so a stale file is not left on screen', async () => {
    stubApi(() => ({
      status: 409,
      body: { detail: 'That file is not in the list any more' },
    }))
    const user = userEvent.setup()
    const { onAnswered, onChanged } = show([waitingItem()])
    await user.click(screen.getByRole('radio', { name: 'Home' }))
    await user.click(screen.getByRole('button', { name: 'File it' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('not in the list any more')
    expect(onAnswered).not.toHaveBeenCalled()
    expect(onChanged).toHaveBeenCalled()
  })

  test('the button says what the chosen answer does', async () => {
    stubApi(() => OK)
    const user = userEvent.setup()
    show([
      waitingItem({
        reasons: ['duplicate'],
        question: {
          reason: 'duplicate',
          text: 'This is the same file as a.pdf. Discard this copy, or keep both?',
          answer_kind: 'copy',
          options: [
            { value: 'discard', label: 'Discard this copy' },
            { value: 'keep_both', label: 'Keep both' },
          ],
          field: null,
        },
      }),
    ])
    await user.click(screen.getByRole('radio', { name: 'Discard this copy' }))
    expect(screen.getByRole('button', { name: 'Discard it' })).toBeEnabled()
    await user.click(screen.getByRole('radio', { name: 'Keep both' }))
    expect(screen.getByRole('button', { name: 'File it' })).toBeEnabled()
  })

  test('answering moves focus to the next file question, or to the empty sentence', async () => {
    stubApi(() => OK)
    const user = userEvent.setup()
    const { rerender, onChanged, onAnswered } = show([waitingItem(), SECOND])
    await user.click(screen.getByRole('radio', { name: 'Home' }))
    await user.click(screen.getByRole('button', { name: 'File it' }))
    const heading = await screen.findByRole('heading', { level: 2 })
    expect(screen.getByRole('img', { name: /prescription-2\.pdf/ })).toBeInTheDocument()
    expect(heading).toHaveFocus()
    // The list is read again and the answered file is gone: the last one is answered too.
    rerender(
      <NeedsALook items={[SECOND]} focus={null} onChanged={onChanged} onAnswered={onAnswered} />,
    )
    await user.click(screen.getByRole('radio', { name: 'Home' }))
    await user.click(screen.getByRole('button', { name: 'File it' }))
    rerender(<NeedsALook items={[]} focus={null} onChanged={onChanged} onAnswered={onAnswered} />)
    const empty = screen.getByText('Nothing waiting. New files are read as they arrive.')
    expect(empty).toHaveFocus()
  })

  test('discarding the only copy asks to confirm first', async () => {
    const { calls } = stubApi(() => OK)
    const user = userEvent.setup()
    const damaged = waitingItem({
      reasons: ['damaged'],
      question: {
        reason: 'damaged',
        text: 'I cannot read this file (it is damaged). Discard it, or drop a PDF or a photo instead.',
        answer_kind: 'discard',
        options: [{ value: 'discard', label: 'Discard' }],
        field: null,
      },
    })
    show([damaged])
    await user.click(screen.getByRole('radio', { name: 'Discard' }))
    await user.click(screen.getByRole('button', { name: 'Discard' }))
    expect(calls).toHaveLength(0)
    expect(screen.getByText(/deletes the only copy/)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Yes, discard it' }))
    expect(calls[0]).toMatchObject({
      path: '/v1/needs-a-look/7/answer',
      body: { kind: 'discard', value: 'discard', confirm: true },
    })
  })

  test('keeping the file after the question to confirm sends nothing', async () => {
    const { calls } = stubApi(() => OK)
    const user = userEvent.setup()
    show([
      waitingItem({
        question: {
          reason: 'damaged',
          text: 'Damaged.',
          answer_kind: 'discard',
          options: [{ value: 'discard', label: 'Discard' }],
          field: null,
        },
      }),
    ])
    await user.click(screen.getByRole('radio', { name: 'Discard' }))
    await user.click(screen.getByRole('button', { name: 'Discard' }))
    await user.click(screen.getByRole('button', { name: 'Keep it' }))
    expect(calls).toHaveLength(0)
    expect(screen.queryByText(/deletes the only copy/)).not.toBeInTheDocument()
  })

  test('a copy is answered as a copy and needs no confirmation', async () => {
    const { calls } = stubApi(() => OK)
    const user = userEvent.setup()
    show([
      waitingItem({
        reasons: ['duplicate'],
        question: {
          reason: 'duplicate',
          text: 'This is the same file as a.pdf. Discard this copy, or keep both?',
          answer_kind: 'copy',
          options: [
            { value: 'discard', label: 'Discard this copy' },
            { value: 'keep_both', label: 'Keep both' },
          ],
          field: null,
        },
      }),
    ])
    await user.click(screen.getByRole('radio', { name: 'Keep both' }))
    await user.click(screen.getByRole('button', { name: 'File it' }))
    expect(calls[0]?.body).toEqual({ kind: 'copy', value: 'keep_both' })
  })

  test('a missing value is typed, and goes with the field it is for', async () => {
    const { calls } = stubApi(() => OK)
    const user = userEvent.setup()
    show([
      waitingItem({
        reasons: ['missing_required'],
        question: {
          reason: 'missing_required',
          text: 'I could not read the policy number on this health policy. What is it?',
          answer_kind: 'field',
          options: [],
          field: 'policy_number',
        },
      }),
    ])
    await user.type(screen.getByRole('textbox', { name: 'Policy number' }), 'P/21/5')
    await user.keyboard('{Enter}')
    expect(calls[0]?.body).toEqual({ kind: 'field', value: 'P/21/5', field: 'policy_number' })
  })

  test('a locked PDF asks for its password in a dialog', async () => {
    stubApi(() => OK)
    const user = userEvent.setup()
    show([lockedItem()])
    expect(screen.queryByRole('radio')).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Enter the password' }))
    expect(screen.getByRole('dialog', { name: 'Unlock this PDF' })).toBeInTheDocument()
  })

  test('read_failed offers to try again or to say what it is', async () => {
    const { calls } = stubApi(() => OK)
    const user = userEvent.setup()
    show([
      waitingItem({
        reasons: ['read_failed'],
        question: {
          reason: 'read_failed',
          text: 'I could not read this document. Try again, or tell me what it is.',
          answer_kind: 'retry',
          options: [
            { value: 'retry', label: 'Try again' },
            { value: 'health_policy', label: 'Health policy' },
          ],
          field: null,
        },
      }),
    ])
    await user.click(screen.getByRole('radio', { name: 'Health policy' }))
    await user.click(screen.getByRole('button', { name: 'File it' }))
    expect(calls[0]?.body).toEqual({ kind: 'type', value: 'health_policy' })
  })

  test('says "Not sure:" with an icon where the app was unsure', () => {
    stubApi(() => OK)
    show([waitingItem({ reasons: ['person_unsure'] })])
    const note = screen.getByText(/^Not sure:/)
    expect(note).toHaveTextContent('Not sure: the name on it.')
    expect(note.closest('.doubt')?.querySelector('svg')).toHaveAttribute('aria-hidden', 'true')
  })

  test('a locked PDF says why its page is not shown', () => {
    stubApi(() => OK)
    show([lockedItem()])
    fireEvent.error(screen.getByRole('img'))
    expect(
      screen.getByText('This PDF is locked. Its pages show once you enter the password.'),
    ).toBeInTheDocument()
  })

  test('a page that cannot be drawn says so', () => {
    stubApi(() => OK)
    show([waitingItem()])
    fireEvent.error(screen.getByRole('img'))
    expect(screen.getByText('This page cannot be shown.')).toBeInTheDocument()
  })

  test('the file to show can be picked from outside, by its id', () => {
    stubApi(() => OK)
    show([waitingItem(), SECOND], 8)
    expect(screen.getByRole('img', { name: /prescription-2\.pdf/ })).toBeInTheDocument()
  })

  test('says so when nothing is waiting', () => {
    stubApi(() => OK)
    show([])
    expect(
      screen.getByText('Nothing waiting. New files are read as they arrive.'),
    ).toBeInTheDocument()
  })

  test('shows the refusal sentence of the API', async () => {
    stubApi(() => ({
      status: 409,
      body: { detail: 'This file is being worked on. Try again in a moment' },
    }))
    const user = userEvent.setup()
    show([waitingItem()])
    await user.click(screen.getByRole('radio', { name: 'Home' }))
    await user.click(screen.getByRole('button', { name: 'File it' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('being worked on')
  })

  test('the question comes before the page image, so the task is first', () => {
    stubApi(() => OK)
    show([waitingItem()])
    const question = document.querySelector('.question')!
    const page = document.querySelector('.inbox-page')!
    expect(question.compareDocumentPosition(page) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  })

  test('a disabled File it says what enables it, and stops once an answer is chosen', async () => {
    stubApi(() => OK)
    const user = userEvent.setup()
    show([waitingItem()])
    const file = screen.getByRole('button', { name: 'File it' })
    expect(file).toBeDisabled()
    expect(screen.getByText('Choose who this belongs to')).toBeInTheDocument()
    expect(file).toHaveAccessibleDescription('Choose who this belongs to')
    await user.click(screen.getByRole('radio', { name: 'Home' }))
    expect(screen.queryByText('Choose who this belongs to')).not.toBeInTheDocument()
  })

  test('a missing value says what to type before File it can be pressed', () => {
    stubApi(() => OK)
    show([
      waitingItem({
        reasons: ['missing_required'],
        question: {
          reason: 'missing_required',
          text: 'What is the policy number?',
          answer_kind: 'field',
          options: [],
          field: 'policy_number',
        },
      }),
    ])
    expect(screen.getByText('Type the policy number')).toBeInTheDocument()
  })

  test('the keyboard hint is marked so a phone can hide it', () => {
    stubApi(() => OK)
    show([waitingItem()])
    expect(screen.getByText(/Press 1 to 3 to choose/)).toHaveClass('keys-hint')
  })
})

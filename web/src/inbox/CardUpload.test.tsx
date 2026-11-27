import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, test, vi } from 'vitest'

import { stubApi } from '../test/api.ts'
import { CardUpload } from './CardUpload.tsx'

// Made up for this test: not a real password.
const MASTER_PW = 'test-only-master-pw'

function photo(name: string): File {
  return new File([new Uint8Array([1, 2, 3])], name, { type: 'image/jpeg' })
}

function show(onDone = vi.fn<() => void>()) {
  render(<CardUpload open onClose={vi.fn<() => void>()} onDone={onDone} />)
  return { onDone }
}

// stubApi keeps JSON bodies only; a form is read back from the fetch call itself.
function sentForm(fetchMock: ReturnType<typeof stubApi>['fetchMock']): FormData {
  return fetchMock.mock.calls[0]![1]!.body as FormData
}

describe('CardUpload', () => {
  test('focus is on the first field when it opens', () => {
    stubApi(() => undefined)
    show()
    expect(screen.getByLabelText('Front of the card')).toHaveFocus()
  })

  test('card upload posts front, back and master password and shows the result', async () => {
    const { fetchMock } = stubApi(() => ({ body: { status: 'filed', document_id: 'doc-x' } }))
    const user = userEvent.setup()
    const { onDone } = show()
    await user.upload(screen.getByLabelText('Front of the card'), photo('front.jpg'))
    await user.upload(screen.getByLabelText('Back of the card (optional)'), photo('back.jpg'))
    await user.type(screen.getByLabelText('Master password'), MASTER_PW)
    await user.click(screen.getByRole('button', { name: 'Upload the card' }))
    const form = sentForm(fetchMock)
    expect(fetchMock.mock.calls[0]![0]).toBe('/v1/cards')
    expect(form).toBeInstanceOf(FormData)
    expect((form.get('front') as File).name).toBe('front.jpg')
    expect((form.get('back') as File).name).toBe('back.jpg')
    expect(form.get('master_password')).toBe(MASTER_PW)
    expect(await screen.findByRole('status')).toHaveTextContent('Filed')
    expect(onDone).toHaveBeenCalled()
    // The number never comes back, so there is nothing of the card to show.
    expect(document.body.textContent).not.toContain(MASTER_PW)
  })

  test('says waiting when the card needs an answer, and sends no back when there is none', async () => {
    const { fetchMock } = stubApi(() => ({ body: { status: 'asked', item_id: 9 } }))
    const user = userEvent.setup()
    show()
    await user.upload(screen.getByLabelText('Front of the card'), photo('front.jpg'))
    await user.type(screen.getByLabelText('Master password'), MASTER_PW)
    await user.click(screen.getByRole('button', { name: 'Upload the card' }))
    expect(await screen.findByRole('status')).toHaveTextContent('Waiting')
    expect(sentForm(fetchMock).has('back')).toBe(false)
  })

  test('the password is cleared once sent, even when the upload is refused', async () => {
    stubApi(() => ({
      status: 422,
      body: {
        detail: 'That photo could not be used. Upload a clearer, straighter photo of the card.',
      },
    }))
    const user = userEvent.setup()
    show()
    await user.upload(screen.getByLabelText('Front of the card'), photo('front.jpg'))
    await user.type(screen.getByLabelText('Master password'), MASTER_PW)
    await user.click(screen.getByRole('button', { name: 'Upload the card' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'That photo could not be used. Upload a clearer',
    )
    expect(screen.getByLabelText('Master password')).toHaveValue('')
  })

  test('needs a front photo and the master password before it sends anything', async () => {
    const { calls } = stubApi(() => undefined)
    const user = userEvent.setup()
    show()
    await user.click(screen.getByRole('button', { name: 'Upload the card' }))
    expect(screen.getByRole('alert')).toHaveTextContent('Choose the front of the card.')
    await user.upload(screen.getByLabelText('Front of the card'), photo('front.jpg'))
    await user.click(screen.getByRole('button', { name: 'Upload the card' }))
    expect(screen.getByRole('alert')).toHaveTextContent('Type the master password.')
    expect(calls).toHaveLength(0)
  })
})

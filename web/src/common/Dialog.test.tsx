import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { describe, expect, test } from 'vitest'

import { Dialog } from './Dialog.tsx'

function Host() {
  const [open, setOpen] = useState(false)
  return (
    <>
      <button type="button" onClick={() => setOpen(true)}>
        Open it
      </button>
      <Dialog open={open} title="Ask me" onClose={() => setOpen(false)}>
        <label>
          Name <input type="text" />
        </label>
        <button type="button">Go</button>
      </Dialog>
    </>
  )
}

describe('Dialog', () => {
  test('shows nothing until opened, then names itself and takes the focus', async () => {
    const user = userEvent.setup()
    render(<Host />)
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Open it' }))
    expect(screen.getByRole('dialog', { name: 'Ask me' })).toBeInTheDocument()
    expect(screen.getByRole('textbox', { name: 'Name' })).toHaveFocus()
  })

  test('Escape closes it and the focus goes back to the button that opened it', async () => {
    const user = userEvent.setup()
    render(<Host />)
    const opener = screen.getByRole('button', { name: 'Open it' })
    await user.click(opener)
    await user.keyboard('{Escape}')
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(opener).toHaveFocus()
  })

  test('its contents are gone when closed, so nothing typed survives', async () => {
    const user = userEvent.setup()
    render(<Host />)
    await user.click(screen.getByRole('button', { name: 'Open it' }))
    await user.type(screen.getByRole('textbox'), 'abc')
    await user.keyboard('{Escape}')
    await user.click(screen.getByRole('button', { name: 'Open it' }))
    expect(screen.getByRole('textbox')).toHaveValue('')
  })
})

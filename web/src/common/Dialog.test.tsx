import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useEffect, useState } from 'react'
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

  test('a field that appears after it opened (loaded content) takes the focus', async () => {
    function Late() {
      const [ready, setReady] = useState(false)
      useEffect(() => {
        const timer = setTimeout(() => setReady(true), 20)
        return () => clearTimeout(timer)
      }, [])
      return ready ? <input aria-label="Late field" /> : <p>Loading</p>
    }
    render(
      <Dialog open title="Ask me" onClose={() => undefined}>
        <Late />
      </Dialog>,
    )
    await waitFor(() => expect(screen.getByLabelText('Late field')).toHaveFocus())
  })

  test('a field the person already moved to is not taken from them', async () => {
    const user = userEvent.setup()
    function Two() {
      const [more, setMore] = useState(false)
      return (
        <>
          <input aria-label="First" />
          <button type="button" onClick={() => setMore(true)}>
            More
          </button>
          {more && <input aria-label="Added" />}
        </>
      )
    }
    render(
      <Dialog open title="Ask me" onClose={() => undefined}>
        <Two />
      </Dialog>,
    )
    await user.click(screen.getByRole('button', { name: 'More' }))
    await new Promise((resolve) => setTimeout(resolve, 10))
    expect(screen.getByRole('button', { name: 'More' })).toHaveFocus()
  })
})

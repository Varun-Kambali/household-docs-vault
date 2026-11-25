import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, test } from 'vitest'

import { Masked } from './Masked.tsx'

describe('Masked', () => {
  test('shows the last four and the rest as dots until Show is pressed', async () => {
    const user = userEvent.setup()
    render(<Masked value="2345 6789 0123" label="Aadhaar number" />)
    expect(screen.getByText('•••• 0123')).toBeInTheDocument()
    expect(screen.queryByText('2345 6789 0123')).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Show Aadhaar number' }))
    expect(screen.getByText('2345 6789 0123')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Hide Aadhaar number' }))
    expect(screen.queryByText('2345 6789 0123')).not.toBeInTheDocument()
  })

  test('a new value starts hidden again', async () => {
    const user = userEvent.setup()
    const { rerender } = render(<Masked key="a" value="1111 2222 3333" label="number" />)
    await user.click(screen.getByRole('button', { name: 'Show number' }))
    rerender(<Masked key="b" value="4444 5555 6666" label="number" />)
    expect(screen.queryByText('4444 5555 6666')).not.toBeInTheDocument()
  })
})

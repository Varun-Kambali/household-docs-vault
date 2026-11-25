import { render, screen } from '@testing-library/react'
import { describe, expect, test } from 'vitest'

import { Region } from './Region.tsx'

describe('Region, four states', () => {
  test('loading says what is loading and is a busy status', () => {
    render(
      <Region state="loading" what="the list">
        full
      </Region>,
    )
    expect(screen.getByRole('status')).toHaveTextContent('Loading the list')
    expect(screen.queryByText('full')).not.toBeInTheDocument()
  })

  test('empty shows its sentence', () => {
    render(
      <Region state="empty" empty="Nothing here yet.">
        full
      </Region>,
    )
    expect(screen.getByText('Nothing here yet.')).toBeInTheDocument()
  })

  test('error is an alert with the sentence the API gave', () => {
    render(
      <Region state="error" error="The vault is not answering.">
        full
      </Region>,
    )
    expect(screen.getByRole('alert')).toHaveTextContent('The vault is not answering.')
  })

  test('full shows the content', () => {
    render(<Region state="full">full</Region>)
    expect(screen.getByText('full')).toBeInTheDocument()
  })
})

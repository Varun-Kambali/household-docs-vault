import { render, screen } from '@testing-library/react'
import { expect, test } from 'vitest'

import { NoAnswer } from './NoAnswer.tsx'

test('a person the household does not have is named without the kind prefix', () => {
  render(<NoAnswer reason="unknown_person" unread={['person: Anil']} hasRows={false} />)
  expect(screen.getByText('No one called Anil is in the household.')).toBeInTheDocument()
})

import { fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, test, vi } from 'vitest'

import type { PartChange } from '../api/types.ts'
import { listQuery, sentence } from '../test/api.ts'
import { fromQuery } from './listQuery.ts'
import { Sentence } from './Sentence.tsx'

function draw(over: Partial<Parameters<typeof Sentence>[0]> = {}) {
  const onChange = vi.fn<(change: PartChange) => void>()
  const props = {
    sentence: sentence(),
    query: fromQuery(listQuery()),
    unread: [],
    updating: false,
    onChange,
    ...over,
  }
  render(<Sentence {...props} />)
  return onChange
}

const menu = (name: string) => screen.getByRole('combobox', { name })

describe('the adjustable sentence', () => {
  test('each part is a native select showing what the query says', () => {
    draw({ query: fromQuery(listQuery({ types: ['life_policy'], people: ['p2'] })) })
    expect(menu('Kind of document')).toHaveDisplayValue('Life policy')
    expect(menu('Person')).toHaveDisplayValue('Kavita Rao')
    expect(menu('Which date')).toHaveDisplayValue('expire')
    expect(menu('When')).toHaveDisplayValue('any time')
  })

  test('a part the menu cannot name shows the server words', () => {
    draw({
      query: fromQuery(listQuery({ types: ['health_policy', 'life_policy'] })),
    })
    expect(menu('Kind of document')).toHaveDisplayValue('Health policies')
  })

  test('choosing sends the slot and the value the API offered', async () => {
    const onChange = draw()
    await userEvent.selectOptions(menu('Person'), 'Kavita Rao')
    expect(onChange).toHaveBeenLastCalledWith({ slot: 'who', value: 'p2' })
    await userEvent.selectOptions(menu('Person'), 'everyone')
    expect(onChange).toHaveBeenLastCalledWith({ slot: 'who', value: [] })
    await userEvent.selectOptions(menu('When'), 'next 30 days')
    expect(onChange).toHaveBeenLastCalledWith({ slot: 'when', value: 'next_30' })
  })

  test('a custom range asks for two dates with labels and sends both', async () => {
    const onChange = draw()
    await userEvent.selectOptions(menu('When'), 'a custom range')
    expect(onChange).not.toHaveBeenCalled()
    fireEvent.change(screen.getByLabelText('From'), { target: { value: '2026-12-01' } })
    fireEvent.change(screen.getByLabelText('To'), { target: { value: '2027-01-31' } })
    expect(onChange).toHaveBeenLastCalledWith({
      slot: 'when',
      value: { start: '2026-12-01', end: '2027-01-31' },
    })
  })

  test('a range in the query fills the two dates when the custom range is chosen', async () => {
    draw({ query: fromQuery(listQuery({ range: { start: '2026-12-01', end: '2027-01-31' } })) })
    await userEvent.selectOptions(menu('When'), 'a custom range')
    expect(screen.getByLabelText('From')).toHaveValue('2026-12-01')
    expect(screen.getByLabelText('To')).toHaveValue('2027-01-31')
  })

  test('picking another way to say when closes the two dates', async () => {
    draw()
    await userEvent.selectOptions(menu('When'), 'a custom range')
    await userEvent.selectOptions(menu('When'), 'any time')
    expect(screen.queryByLabelText('From')).not.toBeInTheDocument()
  })

  test('a place is shown as words and can be removed', async () => {
    const parts = sentence().parts
    const onChange = draw({
      sentence: sentence({
        parts: [...parts, { slot: 'place', text: 'Bengaluru', value: 'Bengaluru', options: [] }],
      }),
      query: fromQuery(listQuery({ place: 'Bengaluru' })),
    })
    expect(screen.getByText(/from Bengaluru/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Remove the place Bengaluru' }))
    expect(onChange).toHaveBeenCalledWith({ slot: 'place', value: null })
  })

  test('a part the server could not read is said in words, beside the sentence', () => {
    draw({ unread: ['before Diwali'] })
    expect(screen.getByText("Couldn't read: before Diwali")).toBeInTheDocument()
  })

  test('leaves out the kind the server puts before the words it could not read', () => {
    draw({ unread: ['date: before Diwali', 'person: Anil'] })
    expect(screen.getByText("Couldn't read: before Diwali, Anil")).toBeInTheDocument()
  })

  test('says it is updating while a change is on its way', () => {
    draw({ updating: true })
    expect(screen.getByText('Updating the list')).toBeInTheDocument()
  })
})

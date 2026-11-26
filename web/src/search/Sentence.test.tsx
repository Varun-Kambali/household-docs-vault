import { fireEvent, render, screen, within } from '@testing-library/react'
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

  test('a kind part that is one whole area shows the area, not a list of types', () => {
    const base = sentence()
    const seven = [
      'life_policy',
      'health_policy',
      'vehicle_policy',
      'home_policy',
      'travel_policy',
      'gadget_policy',
      'accident_policy',
    ]
    draw({
      sentence: sentence({
        parts: base.parts.map((p) =>
          p.slot === 'what' ? { ...p, text: 'insurance documents', value: 'area:insurance' } : p,
        ),
      }),
      query: fromQuery(listQuery({ types: seven as never })),
    })
    expect(menu('Kind of document')).toHaveDisplayValue('Insurance')
  })

  test('the kind menu groups the areas and the kinds, with all documents first on its own', () => {
    draw()
    const kind = menu('Kind of document')
    const options = within(kind).getAllByRole('option')
    expect(options[0]).toHaveTextContent('all documents')
    expect(options[0]?.closest('optgroup')).toBeNull()
    const areas = within(kind).getByRole('group', { name: 'Areas' })
    expect(
      within(areas)
        .getAllByRole('option')
        .map((o) => o.textContent),
    ).toEqual(['Insurance'])
    const kinds = within(kind).getByRole('group', { name: 'Kinds of document' })
    expect(
      within(kinds)
        .getAllByRole('option')
        .map((o) => o.textContent),
    ).toEqual(['Health policy', 'Life policy'])
  })

  describe('the custom range', () => {
    test('with From after To is not sent, and says so beside the dates', async () => {
      const onChange = draw()
      await userEvent.selectOptions(menu('When'), 'a custom range')
      fireEvent.change(screen.getByLabelText('From'), { target: { value: '2027-02-01' } })
      onChange.mockClear()
      fireEvent.change(screen.getByLabelText('To'), { target: { value: '2027-01-01' } })
      expect(onChange).not.toHaveBeenCalled()
      const note = screen.getByText('From must be on or before To')
      expect(note.querySelector('svg')).not.toBeNull()
      for (const name of ['From', 'To']) {
        const input = screen.getByLabelText(name)
        expect(input).toHaveAttribute('aria-invalid', 'true')
        expect(input).toHaveAttribute('aria-describedby', note.id)
      }
    })

    test('is sent again, and the note goes, once the dates are in order', async () => {
      const onChange = draw()
      await userEvent.selectOptions(menu('When'), 'a custom range')
      fireEvent.change(screen.getByLabelText('From'), { target: { value: '2027-02-01' } })
      fireEvent.change(screen.getByLabelText('To'), { target: { value: '2027-01-01' } })
      fireEvent.change(screen.getByLabelText('To'), { target: { value: '2027-03-01' } })
      expect(screen.queryByText('From must be on or before To')).not.toBeInTheDocument()
      expect(screen.getByLabelText('From')).not.toHaveAttribute('aria-invalid')
      expect(onChange).toHaveBeenLastCalledWith({
        slot: 'when',
        value: { start: '2027-02-01', end: '2027-03-01' },
      })
    })

    test('shows the query range on its own, and follows it when the query changes', () => {
      const first = fromQuery(listQuery({ range: { start: '2026-12-01', end: '2027-01-31' } }))
      const onChange = vi.fn<(change: PartChange) => void>()
      const props = { sentence: sentence(), unread: [], updating: false, onChange }
      const { rerender } = render(<Sentence {...props} query={first} />)
      expect(screen.getByLabelText('From')).toHaveValue('2026-12-01')
      expect(screen.getByLabelText('To')).toHaveValue('2027-01-31')
      const second = fromQuery(listQuery({ range: { start: '2027-03-01', end: '2027-03-31' } }))
      rerender(<Sentence {...props} query={second} />)
      expect(screen.getByLabelText('From')).toHaveValue('2027-03-01')
      expect(screen.getByLabelText('To')).toHaveValue('2027-03-31')
    })
  })
})

import { render, screen, within } from '@testing-library/react'
import { describe, expect, test } from 'vitest'

import { row } from '../test/api.ts'
import { ListResults } from './ListResults.tsx'

const PEOPLE = new Map([
  ['p1', 'Ravi Kumar Rao'],
  ['p2', 'Kavita Rao'],
])

function draw(rows = [row()], role: string | null = null) {
  render(<ListResults rows={rows} role={role} people={PEOPLE} />)
}

const items = () => within(screen.getByRole('list', { name: 'Documents' })).getAllByRole('listitem')

describe('the rows of a list', () => {
  test('say how many in plain words', () => {
    draw([row({ document_id: 'a' }), row({ document_id: 'b' })])
    expect(screen.getByText('2 documents')).toBeInTheDocument()
  })

  test('say one document in the singular', () => {
    draw()
    expect(screen.getByText('1 document')).toBeInTheDocument()
  })

  test('show the date, the kind, the people, the key fields and the path on one line', () => {
    draw([
      row({
        date: '2027-09-19',
        people: ['p2', 'p1'],
        key_fields: { insurer: 'Care Health', end_date: '2027-09-19' },
        field_kinds: { insurer: 'text', end_date: 'date' },
      }),
    ])
    const line = items()[0]!
    expect(within(line).getByText('19 Sep 2027', { selector: 'time' })).toHaveAttribute(
      'datetime',
      '2027-09-19',
    )
    expect(within(line).getByText('Health policy')).toBeInTheDocument()
    expect(within(line).getByText('Kavita Rao, Ravi Kumar Rao')).toBeInTheDocument()
    expect(within(line).getByText('Care Health · 19 Sep 2027')).toBeInTheDocument()
    expect(
      within(line).getByText(/Kavita Rao\/Insurance\/2026-09-20 Health policy/),
    ).toBeInTheDocument()
  })

  test('each row is a link that opens the file', () => {
    draw([row({ document_id: 'doc-7', lines: [] })])
    expect(within(items()[0]!).getByRole('link')).toHaveAttribute('href', '/doc/doc-7?page=1')
  })

  test('rows sit in date order: the soonest first for an expiry', () => {
    draw(
      [
        row({ document_id: 'late', date: '2027-05-01', lines: [] }),
        row({ lines: [], document_id: 'none', date: null }),
        row({ lines: [], document_id: 'soon', date: '2026-12-01' }),
      ],
      'expiry',
    )
    expect(items().map((li) => within(li).getByRole('link').getAttribute('href'))).toEqual([
      '/doc/soon?page=1',
      '/doc/late?page=1',
      '/doc/none?page=1',
    ])
  })

  test('and the newest first when the date is one that has passed', () => {
    draw(
      [
        row({ lines: [], document_id: 'old', date: '2020-05-01' }),
        row({ lines: [], document_id: 'new', date: '2026-12-01' }),
        row({ lines: [], document_id: 'none', date: null }),
      ],
      'purchase',
    )
    expect(items().map((li) => within(li).getByRole('link').getAttribute('href'))).toEqual([
      '/doc/new?page=1',
      '/doc/old?page=1',
      '/doc/none?page=1',
    ])
  })

  test('a row with no date says so in words', () => {
    draw([row({ date: null })])
    expect(within(items()[0]!).getByText('No date')).toBeInTheDocument()
  })

  test('an ID number shows its last four and a card shows only its note', () => {
    draw([
      row({
        document_id: 'a',
        doc_type: 'aadhaar',
        key_fields: { number: '234567890123' },
        field_kinds: { number: 'identifier' },
      }),
      row({ document_id: 'c', doc_type: 'card_front', key_fields: { number: '4111111111111111' } }),
    ])
    expect(screen.getByText('•••• 0123')).toBeInTheDocument()
    expect(screen.queryByText(/4111/)).not.toBeInTheDocument()
    expect(screen.getByText(/Secrets\.kdbx/)).toBeInTheDocument()
  })
})

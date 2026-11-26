import { describe, expect, test } from 'vitest'

import { row } from '../test/api.ts'
import { orderRows } from './order.ts'

const rows = [
  row({ document_id: 'b', date: '2026-03-01' }),
  row({ document_id: 'none', date: null }),
  row({ document_id: 'c', date: '2027-01-15' }),
  row({ document_id: 'a', date: '2025-06-30' }),
]
const ids = (list: { document_id: string }[]) => list.map((r) => r.document_id)

describe('orderRows', () => {
  test.each(['expiry', 'renewal', 'due'])('%s: the soonest first, no date last', (role) => {
    expect(ids(orderRows(rows, role))).toEqual(['a', 'b', 'c', 'none'])
  })

  test.each(['document', 'issue', 'purchase', null])(
    '%s: the newest first, no date last',
    (role) => {
      expect(ids(orderRows(rows, role))).toEqual(['c', 'b', 'a', 'none'])
    },
  )

  test('rows on the same day keep a fixed order, and the input is not changed', () => {
    const tied = [
      row({ document_id: 'y', date: '2026-01-01' }),
      row({ document_id: 'x', date: '2026-01-01' }),
    ]
    expect(ids(orderRows(tied, 'expiry'))).toEqual(['x', 'y'])
    expect(ids(tied)).toEqual(['y', 'x'])
  })
})

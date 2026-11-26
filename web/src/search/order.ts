// The order of a list: a date that is still to come (expiry, renewal, due) puts the soonest
// first, so what needs doing next is on top; any other date (document, issue, purchase, or none
// named) puts the newest first. A row with no date goes last either way. The API sorts oldest
// first for every role, so the screen orders the rows itself.
import type { RowOut } from '../api/types.ts'

const AHEAD = ['expiry', 'renewal', 'due']

export function orderRows(rows: RowOut[], role: string | null): RowOut[] {
  const soonestFirst = role !== null && AHEAD.includes(role)
  return [...rows].sort((a, b) => {
    if (a.date === null || b.date === null) {
      if (a.date !== b.date) return a.date === null ? 1 : -1
    } else if (a.date !== b.date) {
      return (a.date < b.date ? -1 : 1) * (soonestFirst ? 1 : -1)
    }
    return a.document_id < b.document_id ? -1 : a.document_id > b.document_id ? 1 : 0
  })
}

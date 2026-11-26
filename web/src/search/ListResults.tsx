// The rows of a list, one line each in date order, under a count in plain words. Each row is a
// link that opens the file in the viewer, so Tab, Enter and "open in a new tab" all work. The
// date is the one the list is about (the expiry for an expiry list, the document date when no
// date is named), and a row with no such date says so.
import type { RowOut } from '../api/types.ts'
import { formatDate } from '../common/format.ts'
import { CARD_NOTE, isCard, typeLabel } from '../common/labels.ts'
import { keyText } from './rowText.ts'
import { openRow } from './openAt.ts'
import { orderRows } from './order.ts'

// The API stops a list at this many rows (the default limit of Searcher.list in search/retrieve.py).
export const LIST_LIMIT = 500

export function ListResults({
  rows,
  role,
  people,
}: {
  rows: RowOut[]
  role: string | null
  people: ReadonlyMap<string, string>
}) {
  const ordered = orderRows(rows, role)
  return (
    <>
      <p className="list-count">
        {rows.length >= LIST_LIMIT
          ? `Showing the first ${LIST_LIMIT} documents`
          : `${rows.length} ${rows.length === 1 ? 'document' : 'documents'}`}
      </p>
      <ul className="list-rows" aria-label="Documents">
        {ordered.map((row) => {
          const names = row.people.map((id) => people.get(id)).filter((name) => name !== undefined)
          return (
            <li key={row.document_id}>
              <a className="list-row" href={openRow(row)}>
                <span className="list-date">
                  {row.date === null ? (
                    'No date'
                  ) : (
                    <time dateTime={row.date}>{formatDate(row.date)}</time>
                  )}
                </span>
                <span className="list-type">{typeLabel(row.doc_type)}</span>
                <span className="list-people">{names.join(', ')}</span>
                <span className="list-fields">
                  {isCard(row.doc_type) ? CARD_NOTE : keyText(row)}
                </span>
                <span className="list-path" title={row.rel_path}>
                  {row.rel_path}
                </span>
              </a>
            </li>
          )
        })}
      </ul>
    </>
  )
}

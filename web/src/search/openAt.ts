// Where a result opens in the viewer: its page (1 in the address, 0 in the API) and the lines
// to outline on it.
import { hrefFor } from '../app/route.ts'

export function openAt(
  documentId: string,
  page: number,
  lineIdxs: number[],
  field?: string,
): string {
  return hrefFor({
    name: 'doc',
    id: documentId,
    page: page + 1,
    lines: lineIdxs.length > 0 ? lineIdxs.join(',') : null,
    ...(field !== undefined && { field }),
  })
}

export function openRow(row: {
  document_id: string
  lines: { page: number; idx: number }[]
}): string {
  const first = row.lines[0]
  if (first === undefined) return openAt(row.document_id, 0, [])
  return openAt(
    row.document_id,
    first.page,
    row.lines.filter((line) => line.page === first.page).map((line) => line.idx),
  )
}

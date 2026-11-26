// The key fields of a row on one line: each by its kind (dates and amounts as the answer writes
// them), an ID number as its last four.
import type { RowOut } from '../api/types.ts'
import { formatField } from '../common/format.ts'
import { isMasked, lastFour } from '../common/labels.ts'

export function keyText(row: RowOut): string {
  return Object.entries(row.key_fields)
    .map(([name, value]) => {
      const text = formatField(row.field_kinds[name], value)
      return isMasked(row.doc_type, name) ? lastFour(text) : text
    })
    .join(' · ')
}

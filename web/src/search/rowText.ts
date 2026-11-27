// The key fields of a row, each its own piece: by its kind (dates and amounts as the answer
// writes them), an ID number as its last four. They are shown side by side or on their own lines,
// never glued into one string. A list's first column already says the row's date, so a field that
// holds that same date is left out there.
import type { RowOut } from '../api/types.ts'
import { formatField } from '../common/format.ts'
import { isMasked, lastFour } from '../common/labels.ts'

export type KeyPart = { name: string; text: string; identifier: boolean }

export function keyParts(row: RowOut, options: { dropRowDate?: boolean } = {}): KeyPart[] {
  return Object.entries(row.key_fields).flatMap(([name, value]) => {
    const kind = row.field_kinds[name]
    if (options.dropRowDate === true && kind === 'date' && value === row.date) return []
    const text = formatField(kind, value)
    return [
      {
        name,
        text: isMasked(row.doc_type, name) ? lastFour(text) : text,
        identifier: kind === 'identifier',
      },
    ]
  })
}

// The quick finder: a listbox the search box drives. Focus stays in the box; the active row is
// named by aria-activedescendant. One line a row: the kind of document, the people, the key
// fields (an ID number as its last four) and where it is filed. Matched words are bold.
import type { ReactNode } from 'react'

import type { RowOut } from '../api/types.ts'
import { formatField } from '../common/format.ts'
import { FINDER_ID, optionId } from './finderIds.ts'
import { CARD_NOTE, isCard, isMasked, lastFour, typeLabel } from '../common/labels.ts'

function words(prompt: string): string[] {
  return prompt
    .split(/\s+/)
    .map((word) => word.replace(/[^\p{L}\p{N}]/gu, ''))
    .filter((word) => word.length >= 2)
}

export function Highlight({ text, prompt }: { text: string; prompt: string }): ReactNode {
  const found = words(prompt)
  if (found.length === 0) return text
  const pattern = new RegExp(
    `(${found.map((w) => w.replace(/[\\^$.*+?()[\]{}|]/g, '\\$&')).join('|')})`,
    'giu',
  )
  return text
    .split(pattern)
    .map((part, index) => (index % 2 === 1 ? <strong key={index}>{part}</strong> : part))
}

function keyText(row: RowOut): string {
  return Object.entries(row.key_fields)
    .map(([name, value]) => {
      const text = formatField(row.field_kinds[name], value)
      return isMasked(row.doc_type, name) ? lastFour(text) : text
    })
    .join(' · ')
}

export function Finder({
  rows,
  prompt,
  people,
  active,
  onOpen,
}: {
  rows: RowOut[]
  prompt: string
  people: ReadonlyMap<string, string>
  active: number
  onOpen: (row: RowOut) => void
}) {
  return (
    // The search box keeps the focus and names the active row, so the rows need no key handlers.
    // oxlint-disable-next-line jsx-a11y/no-noninteractive-element-to-interactive-role, jsx-a11y/prefer-tag-over-role
    <ul id={FINDER_ID} className="finder" role="listbox" aria-label="Matching files">
      {rows.map((row, index) => {
        const names = row.people.map((id) => people.get(id)).filter((name) => name !== undefined)
        const detail = isCard(row.doc_type) ? CARD_NOTE : keyText(row)
        return (
          // oxlint-disable-next-line jsx-a11y/click-events-have-key-events
          <li
            key={row.document_id}
            id={optionId(index)}
            // oxlint-disable-next-line jsx-a11y/no-noninteractive-element-to-interactive-role, jsx-a11y/prefer-tag-over-role
            role="option"
            aria-selected={index === active}
            className="finder-row"
            data-active={index === active}
            onClick={() => onOpen(row)}
          >
            <span className="finder-type">
              <Highlight text={typeLabel(row.doc_type)} prompt={prompt} />
            </span>
            <span className="finder-people">
              <Highlight text={names.join(', ')} prompt={prompt} />
            </span>
            <span className="finder-fields">
              <Highlight text={detail} prompt={prompt} />
            </span>
            <span className="finder-path" title={row.rel_path}>
              <Highlight text={row.rel_path} prompt={prompt} />
            </span>
          </li>
        )
      })}
    </ul>
  )
}

// The sentence over a list: "Showing [health policies] for [everyone] that [expire] [any time]".
// Each part is a native select, so the keyboard and a screen reader get it for free. Choosing
// sends the slot and the value the API offered; the API builds the new query, so no part is
// worked out here. A custom range is two date inputs. A part the server could not read is said
// in words beside the sentence, with an icon, never by colour alone.
import { useId, useState } from 'react'

import type { PartChange, PartOut } from '../api/types.ts'
import type { ListQuery } from './listQuery.ts'
import { unreadWords } from './unread.ts'

const NAMES: Record<string, string> = {
  what: 'Kind of document',
  who: 'Person',
  verb: 'Which date',
  when: 'When',
}
const CURRENT = 'current'
const CUSTOM = 'custom'

// The value the query itself puts on a part, which is what the menu's entries are matched to.
function valueOf(part: PartOut, query: ListQuery): unknown {
  if (part.slot === 'what') {
    // The API names the area when the query lists exactly that area's kinds.
    if (typeof part.value === 'string' && part.options.some((o) => o.value === part.value)) {
      return part.value
    }
    if (query.types.length === 1) return `type:${query.types[0]}`
    if (query.types.length === 0 && query.areas.length === 1) return `area:${query.areas[0]}`
    return query.types.length === 0 && query.areas.length === 0 ? 'all' : CURRENT
  }
  if (part.slot === 'who') {
    if (query.people.length === 0) return []
    return query.people.length === 1 ? query.people[0] : CURRENT
  }
  if (part.slot === 'verb') return query.role ?? 'document'
  if (part.slot === 'when') return query.from === null && query.to === null ? 'any' : CURRENT
  return CURRENT
}

function selected(part: PartOut, query: ListQuery): string {
  const want = JSON.stringify(valueOf(part, query))
  const at = part.options.findIndex((option) => JSON.stringify(option.value) === want)
  return at === -1 ? CURRENT : String(at)
}

// "All documents" first on its own, then the areas, then the single kinds. The value of each is
// its place in the API's list, so the order shown does not change what a pick sends.
function KindOptions({ options }: { options: PartOut['options'] }) {
  const at = (prefix: string) =>
    options.flatMap((option, index) =>
      typeof option.value === 'string' && option.value.startsWith(prefix)
        ? [{ option, index }]
        : [],
    )
  const rest = options.flatMap((option, index) =>
    typeof option.value === 'string' && /^(area|type):/.test(option.value)
      ? []
      : [{ option, index }],
  )
  const group = (label: string, items: ReturnType<typeof at>) =>
    items.length > 0 && (
      <optgroup label={label}>
        {items.map(({ option, index }) => (
          <option key={index} value={String(index)}>
            {option.label}
          </option>
        ))}
      </optgroup>
    )
  return (
    <>
      {rest.map(({ option, index }) => (
        <option key={index} value={String(index)}>
          {option.label}
        </option>
      ))}
      {group('Areas', at('area:'))}
      {group('Kinds of document', at('type:'))}
    </>
  )
}

function Menu({
  part,
  query,
  onPick,
}: {
  part: PartOut
  query: ListQuery
  onPick: (value: unknown) => void
}) {
  const now = selected(part, query)
  return (
    <select
      className="sentence-select"
      aria-label={NAMES[part.slot] ?? part.slot}
      value={now}
      onChange={(event) => {
        const option = part.options[Number(event.target.value)]
        if (option !== undefined) onPick(option.value)
      }}
    >
      {/* What the query says when no menu entry names it, in the server's own words. */}
      {now === CURRENT && (
        <option value={CURRENT} disabled>
          {part.text}
        </option>
      )}
      {part.slot === 'what' ? (
        <KindOptions options={part.options} />
      ) : (
        part.options.map((option, index) => (
          <option key={index} value={String(index)}>
            {option.label}
          </option>
        ))
      )}
    </select>
  )
}

function Range({
  start,
  end,
  onPick,
}: {
  start: string | null
  end: string | null
  onPick: (start: string | null, end: string | null) => void
}) {
  const [from, setFrom] = useState(start ?? '')
  const [to, setTo] = useState(end ?? '')
  // The dates follow the query when it changes under them (back and forward, a new list), but not
  // while the user is typing: their own pick comes back as the same dates.
  const [seen, setSeen] = useState({ start, end })
  if (seen.start !== start || seen.end !== end) {
    setSeen({ start, end })
    setFrom(start ?? '')
    setTo(end ?? '')
  }
  const noteId = useId()
  const inverted = from !== '' && to !== '' && from > to
  function change(nextFrom: string, nextTo: string): void {
    setFrom(nextFrom)
    setTo(nextTo)
    const backwards = nextFrom !== '' && nextTo !== '' && nextFrom > nextTo
    if (!backwards && (nextFrom !== '' || nextTo !== '')) onPick(nextFrom || null, nextTo || null)
  }
  const flag = inverted ? { 'aria-invalid': true, 'aria-describedby': noteId } : {}
  return (
    <div className="sentence-range">
      <label>
        From
        <input
          type="date"
          value={from}
          onChange={(event) => change(event.target.value, to)}
          {...flag}
        />
      </label>
      <label>
        To
        <input
          type="date"
          value={to}
          onChange={(event) => change(from, event.target.value)}
          {...flag}
        />
      </label>
      {inverted && (
        <p className="sentence-range-note" id={noteId}>
          <DoubtIcon />
          From must be on or before To
        </p>
      )}
    </div>
  )
}

function DoubtIcon() {
  return (
    <svg className="doubt-icon" width="16" height="16" viewBox="0 0 16 16" aria-hidden="true">
      <path d="M8 1.5 15 14H1L8 1.5Z" fill="none" stroke="currentColor" strokeWidth="1.5" />
      <path d="M8 6v4" stroke="currentColor" strokeWidth="1.5" />
      <circle cx="8" cy="11.8" r="0.9" fill="currentColor" />
    </svg>
  )
}

export function Sentence({
  sentence,
  query,
  unread,
  updating,
  onChange,
}: {
  sentence: { parts: PartOut[] }
  query: ListQuery
  unread: string[]
  updating: boolean
  onChange: (change: PartChange) => void
}) {
  const [custom, setCustom] = useState(false)
  const part = (slot: string) => sentence.parts.find((p) => p.slot === slot)
  const place = part('place')

  function menu(slot: string) {
    const found = part(slot)
    if (found === undefined) return null
    return (
      <Menu
        part={found}
        query={query}
        onPick={(value) => {
          if (slot === 'when') setCustom(value === CUSTOM)
          if (value === CUSTOM) return
          onChange({ slot, value: value as PartChange['value'] })
        }}
      />
    )
  }

  return (
    <div className="sentence">
      <p className="sentence-line">
        Showing {menu('what')} for {menu('who')} that {menu('verb')} {menu('when')}
        {place !== undefined && (
          <>
            {' '}
            from {place.text}
            <button
              type="button"
              className="link-button"
              aria-label={`Remove the place ${place.text}`}
              onClick={() => onChange({ slot: 'place', value: null })}
            >
              Remove
            </button>
          </>
        )}
      </p>
      {(custom || query.from !== null || query.to !== null) && (
        <Range
          start={query.from}
          end={query.to}
          onPick={(start, end) => onChange({ slot: 'when', value: { start, end } })}
        />
      )}
      {unread.length > 0 && (
        <p className="sentence-doubt">
          <DoubtIcon />
          {`Couldn't read: ${unread.map(unreadWords).join(', ')}`}
        </p>
      )}
      {updating && <output className="region-note">Updating the list</output>}
    </div>
  )
}

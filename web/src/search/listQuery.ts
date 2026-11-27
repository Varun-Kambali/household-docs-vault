// A list as an address: the query that made it, as short params, so a reload or a shared link
// lists again from the same query without asking the model. Lists (people, types, areas) are
// comma-separated; the free-text parts (place, words, and the unread phrases, which can hold a
// comma) are not split. `list=1` stands for a list with nothing set (every document).
import type { QueryIn, QueryOut } from '../api/types.ts'
import { AREAS, isAreaId } from '../app/areas.ts'
import { maskCards } from '../common/maskCards.ts'
import { TYPE_LABELS } from '../common/labels.ts'

export type ListQuery = {
  people: string[]
  types: string[]
  areas: string[]
  role: string | null
  from: string | null
  to: string | null
  place: string | null
  words: string
  unread: string[]
}

export const EMPTY_LIST: ListQuery = {
  people: [],
  types: [],
  areas: [],
  role: null,
  from: null,
  to: null,
  place: null,
  words: '',
  unread: [],
}

const PARAMS = [
  'list',
  'people',
  'types',
  'areas',
  'role',
  'from',
  'to',
  'place',
  'words',
  'unread',
]

// What an area page lists before anything is narrowed: its documents, with nothing else set.
export function areaList(area: string): ListQuery {
  return { ...EMPTY_LIST, areas: [area] }
}

function split(value: string | null): string[] {
  return (value ?? '').split(',').filter((part) => part !== '')
}

export function listParams(list: ListQuery): URLSearchParams {
  const params = new URLSearchParams()
  if (list.people.length > 0) params.set('people', list.people.join(','))
  if (list.types.length > 0) params.set('types', list.types.join(','))
  if (list.areas.length > 0) params.set('areas', list.areas.join(','))
  if (list.role !== null) params.set('role', list.role)
  if (list.from !== null) params.set('from', list.from)
  if (list.to !== null) params.set('to', list.to)
  if (list.place !== null) params.set('place', list.place)
  if (list.words !== '') params.set('words', maskCards(list.words))
  for (const phrase of list.unread) params.append('unread', maskCards(phrase))
  if (params.size === 0) params.set('list', '1')
  return params
}

// Null when the address holds no list at all.
export function listFromParams(params: URLSearchParams): ListQuery | null {
  if (!PARAMS.some((name) => params.has(name))) return null
  const text = (name: string): string | null => {
    const value = params.get(name)
    return value === null || value === '' ? null : value
  }
  return {
    people: split(params.get('people')),
    types: split(params.get('types')),
    areas: split(params.get('areas')),
    role: text('role'),
    from: text('from'),
    to: text('to'),
    place: text('place'),
    words: params.get('words') ?? '',
    unread: params.getAll('unread').filter((phrase) => phrase !== ''),
  }
}

// One string for one query, to tell whether the list on screen is the one the address names.
export function listKey(list: ListQuery): string {
  return listParams(list).toString()
}

export function fromQuery(query: QueryOut): ListQuery {
  return {
    people: query.people,
    types: query.types,
    areas: query.areas,
    role: query.role ?? null,
    from: query.range?.start ?? null,
    to: query.range?.end ?? null,
    place: query.place ?? null,
    words: query.words,
    unread: query.unread,
  }
}

export function toQueryIn(list: ListQuery): QueryIn {
  return {
    intent: 'list',
    people: list.people,
    types: list.types as QueryIn['types'],
    areas: list.areas as QueryIn['areas'],
    field: null,
    role: list.role as QueryIn['role'],
    range: list.from !== null || list.to !== null ? { start: list.from, end: list.to } : null,
    place: list.place,
    words: list.words,
    unread: list.unread,
  }
}

// What the API accepts (QueryIn in api/models.py), so a hand-made or damaged link is turned away
// here, in words, and not posted to come back as a validation message.
const ROLES = ['expiry', 'renewal', 'due', 'purchase', 'issue', 'document']
const MAX_TEXT = 300
const MAX_ID = 64
const MAX_LISTED = 20

function isDate(value: string): boolean {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false
  const at = new Date(`${value}T00:00:00Z`)
  return !Number.isNaN(at.getTime()) && at.toISOString().startsWith(value)
}

// Null when the list is one the API will read; otherwise a short reason, for the log and the tests
// (the screen says it in one plain sentence either way).
export function listProblem(list: ListQuery): string | null {
  if (list.people.length > MAX_LISTED || list.people.some((id) => id.length > MAX_ID)) {
    return 'people'
  }
  const kinds = Object.keys(TYPE_LABELS).length
  if (list.types.length > kinds || list.types.some((type) => !Object.hasOwn(TYPE_LABELS, type))) {
    return 'types'
  }
  if (list.areas.length > AREAS.length || list.areas.some((area) => !isAreaId(area))) {
    return 'areas'
  }
  if (list.role !== null && !ROLES.includes(list.role)) return 'role'
  for (const date of [list.from, list.to]) {
    if (date !== null && !isDate(date)) return 'date'
  }
  const text = [list.place ?? '', list.words, ...list.unread]
  if (text.some((value) => value.length > MAX_TEXT) || list.unread.length > MAX_LISTED) {
    return 'text'
  }
  return null
}

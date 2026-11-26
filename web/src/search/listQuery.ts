// A list as an address: the query that made it, as short params, so a reload or a shared link
// lists again from the same query without asking the model. Lists (people, types, areas) are
// comma-separated; the free-text parts (place, words, and the unread phrases, which can hold a
// comma) are not split. `list=1` stands for a list with nothing set (every document).
import type { QueryIn, QueryOut } from '../api/types.ts'

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
  if (list.words !== '') params.set('words', list.words)
  for (const phrase of list.unread) params.append('unread', phrase)
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

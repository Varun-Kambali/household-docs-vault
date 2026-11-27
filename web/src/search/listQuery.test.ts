import { describe, expect, test } from 'vitest'

import { testCard } from '../test/api.ts'
import { type Route, hrefFor, parseRoute } from '../app/route.ts'
import {
  EMPTY_LIST,
  areaList,
  listFromParams,
  listKey,
  listParams,
  listProblem,
  toQueryIn,
} from './listQuery.ts'

const SAMPLE = {
  ...EMPTY_LIST,
  people: ['p1', 'p2'],
  types: ['health_policy'],
  areas: ['insurance'],
  role: 'expiry',
  from: '2026-12-01',
  to: '2027-01-31',
  place: 'Bengaluru',
  words: 'care health',
  unread: ['before Diwali', 'at home, Pune'],
}

describe('the list in the address', () => {
  test('writes short params, each list comma-separated', () => {
    const params = listParams(SAMPLE)
    expect(params.get('people')).toBe('p1,p2')
    expect(params.get('types')).toBe('health_policy')
    expect(params.get('areas')).toBe('insurance')
    expect(params.get('role')).toBe('expiry')
    expect(params.get('from')).toBe('2026-12-01')
    expect(params.get('to')).toBe('2027-01-31')
    expect(params.get('place')).toBe('Bengaluru')
    expect(params.get('words')).toBe('care health')
    expect(params.getAll('unread')).toEqual(['before Diwali', 'at home, Pune'])
  })

  test('reads back what it wrote', () => {
    expect(listFromParams(listParams(SAMPLE))).toEqual(SAMPLE)
  })

  test('no params at all is no list, and an empty list carries a marker', () => {
    expect(listFromParams(new URLSearchParams(''))).toBeNull()
    expect(listFromParams(new URLSearchParams('q=policy'))).toBeNull()
    expect(listParams(EMPTY_LIST).toString()).toBe('list=1')
    expect(listFromParams(new URLSearchParams('list=1'))).toEqual(EMPTY_LIST)
  })

  test('leaves out what is empty and the marker when something is set', () => {
    expect(listParams({ ...EMPTY_LIST, role: 'due' }).toString()).toBe('role=due')
  })

  test('drops empty ids from a comma list', () => {
    expect(listFromParams(new URLSearchParams('people=p1,,p2,'))?.people).toEqual(['p1', 'p2'])
  })

  test('the key is the same for the same query however it was made', () => {
    expect(listKey(SAMPLE)).toBe(listKey(listFromParams(listParams(SAMPLE))!))
    expect(listKey(EMPTY_LIST)).not.toBe(listKey(areaList('rent')))
  })

  test('the API body carries both dates of a range, or none', () => {
    expect(toQueryIn(SAMPLE).range).toEqual({ start: '2026-12-01', end: '2027-01-31' })
    expect(toQueryIn({ ...SAMPLE, to: null }).range).toEqual({ start: '2026-12-01', end: null })
    expect(toQueryIn(EMPTY_LIST).range).toBeNull()
    expect(toQueryIn(EMPTY_LIST).intent).toBe('list')
  })
})

describe('the list in the routes', () => {
  test('the search route keeps its prompt, or a list', () => {
    expect(parseRoute('/', '?q=policies')).toEqual({ name: 'search', q: 'policies' })
    expect(parseRoute('/', '?role=expiry&people=p1')).toEqual({
      name: 'search',
      q: '',
      list: { ...EMPTY_LIST, role: 'expiry', people: ['p1'] },
    })
  })

  test('an area page lists its area until the address says otherwise', () => {
    expect(parseRoute('/area/rent', '')).toEqual({ name: 'area', area: 'rent' })
    expect(parseRoute('/area/rent', '?areas=rent&people=p1')).toEqual({
      name: 'area',
      area: 'rent',
      list: { ...EMPTY_LIST, areas: ['rent'], people: ['p1'] },
    })
  })

  test('hrefFor writes what parseRoute reads', () => {
    const search: Route = { name: 'search', q: '', list: SAMPLE }
    const [path = '', query = ''] = hrefFor(search).split('?')
    expect(parseRoute(path, `?${query}`)).toEqual(search)
    const area: Route = { name: 'area', area: 'rent', list: { ...EMPTY_LIST, people: ['p1'] } }
    expect(hrefFor(area)).toBe('/area/rent?people=p1')
    expect(hrefFor({ name: 'area', area: 'rent' })).toBe('/area/rent')
  })
})

describe('a list the app can read', () => {
  const bad = (over: Partial<typeof SAMPLE>) => listProblem({ ...SAMPLE, ...over })

  test('is one whose parts are all ones the API knows', () => {
    expect(listProblem(SAMPLE)).toBeNull()
    expect(listProblem(EMPTY_LIST)).toBeNull()
    expect(listProblem(areaList('rent'))).toBeNull()
  })

  test('is not one with an unknown role, kind, area or date', () => {
    expect(bad({ role: 'bogus' })).not.toBeNull()
    expect(bad({ types: ['health_policy', 'mystery'] })).not.toBeNull()
    expect(bad({ areas: ['nowhere'] })).not.toBeNull()
    expect(bad({ from: 'garbage' })).not.toBeNull()
    expect(bad({ to: '2027-02-30' })).not.toBeNull()
    expect(bad({ from: '2027-1-5' })).not.toBeNull()
  })

  test('is not one with a value that is too long or too many values', () => {
    expect(bad({ place: 'x'.repeat(301) })).not.toBeNull()
    expect(bad({ words: 'x'.repeat(301) })).not.toBeNull()
    expect(bad({ unread: ['x'.repeat(301)] })).not.toBeNull()
    expect(bad({ people: Array.from({ length: 21 }, (_, i) => `p${i}`) })).not.toBeNull()
    expect(bad({ people: ['p'.repeat(65)] })).not.toBeNull()
    expect(bad({ place: 'x'.repeat(300) })).toBeNull()
  })
})

describe('what the address may carry', () => {
  test('a card number in the words or an unread phrase keeps only its last four', () => {
    const card = testCard()
    const params = listParams({ ...EMPTY_LIST, words: `bill ${card}`, unread: [`on ${card}`] })
    expect(params.toString()).not.toContain(card)
    expect(params.get('words')).toContain(card.slice(-4))
    expect(params.getAll('unread')[0]).toContain(card.slice(-4))
  })

  test('a link with too many types or areas is unreadable', () => {
    expect(listProblem({ ...EMPTY_LIST, types: Array(70).fill('health_policy') })).toBe('types')
    expect(listProblem({ ...EMPTY_LIST, areas: Array(30).fill('insurance') })).toBe('areas')
  })
})

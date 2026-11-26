import { describe, expect, test } from 'vitest'

import { parseRoute, hrefFor } from '../app/route.ts'
import {
  EMPTY_LIST,
  areaList,
  listFromParams,
  listKey,
  listParams,
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
    const search = { name: 'search', q: '', list: SAMPLE } as const
    const [path = '', query = ''] = hrefFor(search).split('?')
    expect(parseRoute(path, `?${query}`)).toEqual(search)
    const area = { name: 'area', area: 'rent', list: { ...EMPTY_LIST, people: ['p1'] } } as const
    expect(hrefFor(area)).toBe('/area/rent?people=p1')
    expect(hrefFor({ name: 'area', area: 'rent' })).toBe('/area/rent')
  })
})

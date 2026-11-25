import { describe, expect, test } from 'vitest'

import { AREAS } from './areas.ts'
import { hrefFor, parseRoute } from './route.ts'

describe('parseRoute', () => {
  test('/ is search and ?q= holds the prompt', () => {
    expect(parseRoute('/', '')).toEqual({ name: 'search', q: '' })
    expect(parseRoute('/', '?q=kavita%27s%20policy')).toEqual({
      name: 'search',
      q: "kavita's policy",
    })
  })

  test('the viewer takes an id, a page and lines', () => {
    expect(parseRoute('/doc/12', '?page=2&lines=3-5')).toEqual({
      name: 'doc',
      id: '12',
      page: 2,
      lines: '3-5',
    })
    expect(parseRoute('/doc/12', '')).toEqual({ name: 'doc', id: '12', page: 0, lines: null })
  })

  test('a page that is not a number counts as the first', () => {
    expect(parseRoute('/doc/12', '?page=abc')).toMatchObject({ page: 0 })
    expect(parseRoute('/doc/12', '?page=-4')).toMatchObject({ page: 0 })
  })

  test('inbox and each area are routes, and anything else is not found', () => {
    expect(parseRoute('/inbox', '')).toEqual({ name: 'inbox' })
    expect(parseRoute('/inbox/', '')).toEqual({ name: 'inbox' })
    expect(parseRoute('/area/tax', '')).toEqual({ name: 'area', area: 'tax' })
    expect(parseRoute('/area/nonsense', '')).toEqual({ name: 'notfound' })
    expect(parseRoute('/doc/', '')).toEqual({ name: 'notfound' })
    expect(parseRoute('/elsewhere', '')).toEqual({ name: 'notfound' })
  })
})

describe('hrefFor', () => {
  test('writes the addresses parseRoute reads', () => {
    expect(hrefFor({ name: 'search', q: 'a b' })).toBe('/?q=a+b')
    expect(hrefFor({ name: 'search', q: '' })).toBe('/')
    expect(hrefFor({ name: 'inbox' })).toBe('/inbox')
    expect(hrefFor({ name: 'area', area: 'rent' })).toBe('/area/rent')
    expect(hrefFor({ name: 'doc', id: '7', page: 1, lines: '2-4' })).toBe('/doc/7?page=1&lines=2-4')
    expect(hrefFor({ name: 'doc', id: '7', page: 0, lines: null })).toBe('/doc/7')
  })
})

describe('AREAS', () => {
  test('lists the twelve areas in the order of the vault', () => {
    expect(AREAS.map((a) => a.id)).toEqual([
      'insurance',
      'purchases',
      'identity',
      'vehicle',
      'work',
      'education',
      'tax',
      'cards',
      'medical',
      'property',
      'rent',
      'utilities',
    ])
    expect(AREAS[0]?.label).toBe('Insurance')
  })
})

import { describe, expect, test } from 'vitest'

import { parseLines } from './lines.ts'

describe('parseLines', () => {
  test('reads numbers, lists and ranges', () => {
    expect(parseLines('3')).toEqual([3])
    expect(parseLines('3,5')).toEqual([3, 5])
    expect(parseLines('2-4')).toEqual([2, 3, 4])
    expect(parseLines('1,3-4')).toEqual([1, 3, 4])
  })
  test('drops what is not a line, and caps a range', () => {
    expect(parseLines(null)).toEqual([])
    expect(parseLines('x,-1,4-2,7')).toEqual([7])
    expect(parseLines('0-100000').length).toBeLessThanOrEqual(200)
  })
})

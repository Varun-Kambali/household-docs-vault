import { describe, expect, test } from 'vitest'

import { testCard } from '../test/api.ts'
import { maskCards } from './maskCards.ts'

const spaced = (n: string) => n.replace(/(.{4})/g, '$1 ').trim()

describe('maskCards', () => {
  test('keeps only the last four of a number that passes Luhn', () => {
    const card = testCard()
    expect(maskCards(`bill ${card} paid`)).toBe(`bill •••• ${card.slice(-4)} paid`)
  })
  test('finds it with spaces or dashes between the digits', () => {
    const card = testCard()
    expect(maskCards(spaced(card))).toBe(`•••• ${card.slice(-4)}`)
    expect(maskCards(spaced(card).replaceAll(' ', '-'))).toBe(`•••• ${card.slice(-4)}`)
  })
  test('masks 13 and 19 digit numbers too', () => {
    for (const length of [13, 19]) {
      const card = testCard('4', length)
      expect(maskCards(card)).not.toContain(card.slice(0, 9))
    }
  })
  test('leaves a number that fails Luhn, and short numbers, alone', () => {
    const card = testCard()
    const bad = card.slice(0, -1) + String((Number(card.at(-1)) + 1) % 10)
    expect(maskCards(bad)).toBe(bad)
    expect(maskCards('policy 123456789012')).toBe('policy 123456789012')
    expect(maskCards('on 12 03 2026')).toBe('on 12 03 2026')
  })
})

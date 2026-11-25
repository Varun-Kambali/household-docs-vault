import { describe, expect, test } from 'vitest'

import { isCard, isMasked, lastFour, typeLabel } from './labels.ts'

describe('labels', () => {
  test('a type has its label, and an unknown one shows as it is', () => {
    expect(typeLabel('health_policy')).toBe('Health policy')
    expect(typeLabel('mystery')).toBe('mystery')
  })

  test('only the number of an ID type is masked', () => {
    expect(isMasked('aadhaar', 'number')).toBe(true)
    expect(isMasked('aadhaar', 'holder')).toBe(false)
    expect(isMasked('health_policy', 'number')).toBe(false)
  })

  test('the card types are the three card documents', () => {
    expect(isCard('card_front')).toBe(true)
    expect(isCard('card_statement')).toBe(true)
    expect(isCard('tax_invoice')).toBe(false)
  })

  test('the last four are kept and the rest is dots', () => {
    expect(lastFour('2345 6789 0123')).toBe('•••• 0123')
    expect(lastFour('12')).toBe('••••')
  })
})

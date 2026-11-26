import { describe, expect, test } from 'vitest'

import { formatAmount, formatDate, formatField } from './format.ts'

describe('formatting a stored value by its kind', () => {
  test('an amount gets Indian grouping and paise only when there are some', () => {
    expect(formatAmount('1000000')).toBe('Rs 10,00,000')
    expect(formatAmount('1234.5')).toBe('Rs 1,234.50')
    expect(formatAmount('999')).toBe('Rs 999')
    expect(formatAmount('12345.00')).toBe('Rs 12,345')
    expect(formatAmount('0.125')).toBe('Rs 0.13')
    expect(formatAmount(250000)).toBe('Rs 2,50,000')
  })

  test('a date reads as day, month name and year', () => {
    expect(formatDate('2027-09-19')).toBe('19 Sep 2027')
    expect(formatDate('2027-01-05')).toBe('5 Jan 2027')
  })

  test('what cannot be read stays as stored', () => {
    expect(formatAmount('about ten lakh')).toBe('about ten lakh')
    expect(formatDate('19/09/2027')).toBe('19/09/2027')
    expect(formatDate('2027-13-45')).toBe('2027-13-45')
  })

  test('formatField picks by kind and leaves identifiers and text alone', () => {
    expect(formatField('amount', '1000000')).toBe('Rs 10,00,000')
    expect(formatField('date', '2027-09-19')).toBe('19 Sep 2027')
    expect(formatField('identifier', 'P/21/2138/5675525')).toBe('P/21/2138/5675525')
    expect(formatField('text', 'Care Health')).toBe('Care Health')
    expect(formatField(undefined, 12)).toBe('12')
    expect(formatField('list', ['a', 'b'])).toBe('a, b')
  })
})

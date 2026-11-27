import { describe, expect, test } from 'vitest'

import { formatWhen, stepLabel, whereFiled } from './steps.ts'

describe('steps', () => {
  test('a step is named in words, and one it does not know is still readable', () => {
    expect(stepLabel('needs_a_look')).toBe('Needs a look')
    expect(stepLabel('kept_both')).toBe('Kept both')
    expect(stepLabel('some_new_step')).toBe('some new step')
  })

  test('a time reads as day, month and time; text that is not a time is left as it is', () => {
    expect(formatWhen('2026-11-26T08:53:07+05:30')).toMatch(/26 Nov/)
    expect(formatWhen('not a time')).toBe('not a time')
  })

  test('where a file went is its folders, and nothing for a file with none', () => {
    expect(whereFiled('Kavita Rao/Health/2026-09-20 Prescription.pdf')).toBe('Kavita Rao / Health')
    expect(whereFiled('Prescription.pdf')).toBeNull()
    expect(whereFiled(null)).toBeNull()
  })
})

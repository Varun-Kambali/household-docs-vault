import { describe, expect, test } from 'vitest'

import { unreadWords } from './unread.ts'

describe('the words of a part the server could not read', () => {
  test('drop the kind the API puts first', () => {
    expect(unreadWords('date: before Diwali')).toBe('before Diwali')
    expect(unreadWords('person: Anil')).toBe('Anil')
  })

  test('leave a phrase with no kind as it is', () => {
    expect(unreadWords('before Diwali')).toBe('before Diwali')
    expect(unreadWords('Note: keep')).toBe('Note: keep')
  })

  test('strip only the first kind', () => {
    expect(unreadWords('person: a: b')).toBe('a: b')
  })
})

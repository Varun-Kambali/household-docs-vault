import { act, fireEvent, render, renderHook, screen } from '@testing-library/react'
import { describe, expect, test, vi } from 'vitest'

import { usePeople } from '../common/usePeople.ts'
import { LINES, PEOPLE, answer, row, stubApi } from '../test/api.ts'
import { AnswerPanel } from './AnswerPanel.tsx'
import { openAt, openRow } from './openAt.ts'
import { reasonSentence } from './reasons.ts'

describe('reasonSentence', () => {
  test('says why in one sentence for each reason', () => {
    expect(reasonSentence('unknown_person', [])).toBe('No one by that name is in the household.')
    expect(reasonSentence('unknown_person', ['Anil'])).toBe(
      'No one called Anil is in the household.',
    )
    expect(reasonSentence('weak_match', [])).toMatch(/closely enough/)
    expect(reasonSentence('no_field', [])).toMatch(/not that detail/)
    expect(reasonSentence('not_on_page', [])).toMatch(/will not guess/)
    expect(reasonSentence('no_documents', [])).toBe('No file matches that.')
  })
})

describe('openAt', () => {
  test('the page counts from 1 in the address and the lines are listed', () => {
    expect(openAt('d', 0, [])).toBe('/doc/d?page=1')
    expect(openAt('d', 1, [2, 3])).toBe('/doc/d?page=2&lines=2%2C3')
  })
  test('a row opens at its first matched page and only that page lines', () => {
    const lines = [
      { page: 1, idx: 4, bbox: [0, 0, 1, 1] as [number, number, number, number] },
      { page: 0, idx: 1, bbox: [0, 0, 1, 1] as [number, number, number, number] },
      { page: 1, idx: 6, bbox: [0, 0, 1, 1] as [number, number, number, number] },
    ]
    expect(openRow({ document_id: 'd', lines })).toBe('/doc/d?page=2&lines=4%2C6')
    expect(openRow({ document_id: 'd', lines: [] })).toBe('/doc/d?page=1')
  })
})

describe('AnswerPanel', () => {
  test('a page that cannot be drawn says so, and a card keeps its number out of sight', () => {
    stubApi((call) => (call.path.endsWith('/lines') ? { body: LINES } : undefined))
    render(<AnswerPanel answer={answer()} row={row()} onReveal={() => undefined} />)
    const image = screen.getByRole('img', { name: /Page 1/ })
    fireEvent.load(image)
    fireEvent.error(image)
    expect(screen.getByText('The page image is not available.')).toBeInTheDocument()
  })

  test('a card answer shows the note and fetches no page image', () => {
    stubApi(() => undefined)
    render(
      <AnswerPanel
        answer={answer()}
        row={row({ doc_type: 'card_front' })}
        onReveal={() => undefined}
      />,
    )
    expect(screen.getByText(/kept in Secrets.kdbx/)).toBeInTheDocument()
    expect(screen.queryByRole('img')).not.toBeInTheDocument()
  })

  test('an answer whose file is not among the rows still shows its value', () => {
    stubApi(() => undefined)
    render(<AnswerPanel answer={answer()} row={undefined} onReveal={() => undefined} />)
    expect(screen.getByText('P/21/2138/5675525')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Show in folder' })).not.toBeInTheDocument()
  })
})

describe('usePeople', () => {
  test('reads the names once', async () => {
    stubApi(() => ({ body: PEOPLE }))
    const { result } = renderHook(() => usePeople())
    await act(async () => {
      await Promise.resolve()
    })
    expect(result.current.get('p2')).toBe('Kavita Rao')
  })

  test('shows no names when the list cannot be read', async () => {
    stubApi(() => ({ status: 500, body: { detail: 'No.' } }))
    const { result } = renderHook(() => usePeople())
    await act(async () => {
      await Promise.resolve()
    })
    expect(result.current.size).toBe(0)
    vi.unstubAllGlobals()
  })
})

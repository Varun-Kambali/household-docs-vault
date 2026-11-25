// The app declined to answer. It says why in a sentence and never shows a guessed value; the
// closest files are the finder rows under it.
import type { NoAnswerOut } from '../api/types.ts'
import { reasonSentence } from './reasons.ts'

export function NoAnswer({
  reason,
  unread,
  hasRows,
}: {
  reason: NoAnswerOut['reason']
  unread: string[]
  hasRows: boolean
}) {
  return (
    <section className="no-answer" aria-label="No direct answer">
      <p className="no-answer-title">No direct answer.</p>
      <p className="no-answer-reason">{reasonSentence(reason, unread)}</p>
      {hasRows && <p className="hint">The closest files:</p>}
    </section>
  )
}

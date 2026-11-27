// The answer, with the page it came from. The value is the focal point; under it, where it is
// filed; beside it, the page image with the cited lines outlined. Open at page is the one
// primary button.
import { useState, type ReactNode } from 'react'

import type { AnswerOut, RowOut } from '../api/types.ts'
import { CARD_NOTE, isCard } from '../common/labels.ts'
import { Masked } from '../common/Masked.tsx'
import { useLines } from '../common/useLines.ts'
import { Outlines } from '../viewer/Outlines.tsx'
import { navigate } from '../app/location.ts'
import { openAt } from './openAt.ts'

function fieldLabel(field: string): string {
  const spaced = field.replace(/_/g, ' ')
  return spaced.charAt(0).toUpperCase() + spaced.slice(1)
}

export function AnswerPanel({
  answer,
  row,
  onReveal,
  reading = null,
}: {
  answer: AnswerOut
  row: RowOut | undefined
  onReveal: (row: RowOut) => void
  // What the app understood the question to be, to adjust.
  reading?: ReactNode
}) {
  const [failed, setFailed] = useState(false)
  const [ratio, setRatio] = useState<number | null>(null)
  const cited = answer.lines.filter((line) => line.page === answer.page)
  const card = row !== undefined && isCard(row.doc_type)
  // A card's page is never drawn here, so its lines are not fetched either.
  const { texts } = useLines(card ? null : answer.document_id, answer.page)
  const idxs = cited.map((line) => line.idx)
  const id = encodeURIComponent(answer.document_id)
  return (
    <section className="answer" aria-label="Answer">
      <div className="answer-text">
        <p className="answer-value">
          {answer.masked ? (
            <Masked value={answer.text} label={fieldLabel(answer.field).toLowerCase()} />
          ) : (
            answer.text
          )}
        </p>
        <p className="answer-meta">{fieldLabel(answer.field)}</p>
        {reading}
        {row !== undefined && (
          <p className="answer-file">
            <span className="answer-path">{row.rel_path}</span>
            <span className="answer-page">Page {answer.page + 1}</span>
          </p>
        )}
        {card && <p className="hint">{CARD_NOTE}</p>}
        <div className="actions">
          <button
            type="button"
            className="button button-primary"
            onClick={() => navigate(openAt(answer.document_id, answer.page, idxs))}
          >
            Open at page
          </button>
          {row !== undefined && (
            <button type="button" className="button" onClick={() => onReveal(row)}>
              Show in folder
            </button>
          )}
        </div>
      </div>
      {!card && (
        <div className="answer-page-image">
          {failed ? (
            <p className="region-empty">The page image is not available.</p>
          ) : (
            <div
              className="page-frame"
              style={ratio === null ? undefined : { aspectRatio: String(ratio) }}
            >
              <img
                src={`/v1/documents/${id}/pages/${answer.page}.png?width=700`}
                alt={`Page ${answer.page + 1} of the file`}
                onLoad={(event) =>
                  setRatio(
                    event.currentTarget.naturalWidth / (event.currentTarget.naturalHeight || 1),
                  )
                }
                onError={() => setFailed(true)}
              />
              <Outlines
                outlines={cited.map((line) => ({
                  idx: line.idx,
                  bbox: line.bbox,
                  text: texts.get(line.idx),
                }))}
                onOpen={(idx) => navigate(openAt(answer.document_id, answer.page, [idx]))}
              />
            </div>
          )}
        </div>
      )}
    </section>
  )
}

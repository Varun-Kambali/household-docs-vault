// The one question for the file on screen: the question as a heading, the answers as radio rows
// with their full labels, "File it" as the one primary button and "Skip for now" beside it. The
// keys 1 to 9 choose an answer, Enter files it and S skips. A missing value is typed instead, a
// locked PDF opens the unlock dialog, and throwing away the only copy asks first.
import { useEffect, useId, useState } from 'react'

import type { NeedsALookOut } from '../api/types.ts'
import { doubtOf } from './doubt.ts'
import { formatWhen } from './steps.ts'

export type Answer = { kind: string; value: string; field?: string; confirm?: boolean }
export type Seen = { id: number; name: string }

const ONLY_COPY =
  'This deletes the only copy of the file (Drive keeps it in its trash for 30 days). Discard it?'
const TEXT_INPUTS = ['radio', 'checkbox', 'button', 'submit', 'file']

function isTextEntry(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false
  if (target instanceof HTMLInputElement) return !TEXT_INPUTS.includes(target.type)
  return target.isContentEditable || ['TEXTAREA', 'SELECT'].includes(target.tagName)
}

function words(name: string): string {
  const spaced = name.replace(/_/g, ' ')
  return spaced.charAt(0).toUpperCase() + spaced.slice(1)
}

// What the answer is sent as. "Try again" and a document type share one question, so the value
// says which.
function toAnswer(item: NeedsALookOut, value: string, text: string): Answer {
  const { answer_kind: kind, field } = item.question
  if (kind === 'field') return { kind, value: text, field: field ?? '' }
  if (kind === 'retry' && value !== 'retry') return { kind: 'type', value }
  if (kind === 'discard') return { kind, value: 'discard', confirm: true }
  return { kind, value }
}

function Doubt({ what }: { what: string }) {
  return (
    <p className="doubt">
      <svg
        aria-hidden="true"
        width="16"
        height="16"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        <path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3" />
        <path d="M12 9v4" />
        <path d="M12 17h.01" />
      </svg>
      <span>Not sure: {what}.</span>
    </p>
  )
}

export function Question({
  item,
  others,
  chosen,
  onToggle,
  busy,
  error,
  onAnswer,
  onAnswerMany,
  onUnlock,
  onSkip,
}: {
  item: NeedsALookOut
  others: Seen[]
  chosen: ReadonlySet<number>
  onToggle: (id: number) => void
  busy: boolean
  error: string | null
  onAnswer: (answer: Answer) => void
  onAnswerMany: (value: string) => void
  onUnlock: () => void
  onSkip: (() => void) | null
}) {
  const { question } = item
  const kind = question.answer_kind
  const groupName = useId()
  const fieldId = useId()
  const [value, setValue] = useState<string | null>(kind === 'discard' ? 'discard' : null)
  const [text, setText] = useState('')
  const [confirming, setConfirming] = useState(false)
  const radios = kind !== 'field' && kind !== 'unlock'
  const ready = kind === 'field' ? text.trim() !== '' : value !== null
  const doubt = doubtOf(item.reasons)
  const label =
    kind === 'discard' || (kind === 'retry' && value === 'retry')
      ? (question.options.find((o) => o.value === value)?.label ?? 'File it')
      : kind === 'copy' && value === 'discard'
        ? 'Discard it'
        : 'File it'
  // Why File it is not available yet, in the words of the answer it waits for.
  const missing =
    kind === 'field'
      ? `Type the ${words(question.field ?? 'value').toLowerCase()}`
      : kind === 'person'
        ? 'Choose who this belongs to'
        : 'Choose an answer'
  const reasonId = `${groupName}-why`
  const several = chosen.size > 0 && kind === 'person'

  function submit(): void {
    if (!ready || busy) return
    if (kind === 'discard') return setConfirming(true)
    onAnswer(toAnswer(item, value ?? '', text.trim()))
  }

  useEffect(() => {
    function onKey(event: KeyboardEvent): void {
      if (event.metaKey || event.ctrlKey || event.altKey) return
      if (document.querySelector('dialog[open]') !== null || confirming) return
      const target = event.target
      if (isTextEntry(target)) return
      const digit = Number(event.key)
      if (radios && Number.isInteger(digit) && digit >= 1 && digit <= 9) {
        const option = question.options[digit - 1]
        if (option !== undefined) setValue(option.value)
      } else if (event.key === 'Enter' && (target === document.body || isRadio(target))) {
        event.preventDefault()
        submit()
      } else if ((event.key === 's' || event.key === 'S') && onSkip !== null) {
        onSkip()
      }
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  })

  return (
    <div className="question">
      <form
        onSubmit={(event) => {
          event.preventDefault()
          submit()
        }}
      >
        <h2 id={`${groupName}-title`} tabIndex={-1}>
          {question.text}
        </h2>
        <dl className="read">
          <div>
            <dt>File</dt>
            <dd>{item.name}</dd>
          </div>
          <div>
            <dt>Waiting since</dt>
            <dd>
              <time dateTime={item.since}>{formatWhen(item.since)}</time>
            </dd>
          </div>
        </dl>
        {doubt !== null && <Doubt what={doubt} />}
        {radios && (
          <div role="radiogroup" aria-labelledby={`${groupName}-title`} className="choices">
            {question.options.map((option) => (
              <label key={option.value} className="choice" data-checked={value === option.value}>
                <input
                  type="radio"
                  name={groupName}
                  value={option.value}
                  checked={value === option.value}
                  onChange={() => setValue(option.value)}
                />
                <span>{option.label}</span>
              </label>
            ))}
          </div>
        )}
        {kind === 'field' && (
          <div className="field-row">
            <label htmlFor={fieldId}>{words(question.field ?? 'value')}</label>
            <input
              id={fieldId}
              className="prompt"
              type="text"
              value={text}
              autoComplete="off"
              onChange={(event) => setText(event.target.value)}
            />
          </div>
        )}
        {others.length > 0 && kind === 'person' && (
          <fieldset className="same">
            <legend>
              {others.length} more {others.length === 1 ? 'file asks' : 'files ask'} the same thing
            </legend>
            {others.map((other) => (
              <label key={other.id} className="check-row">
                <input
                  type="checkbox"
                  checked={chosen.has(other.id)}
                  onChange={() => onToggle(other.id)}
                />
                <span>{other.name}</span>
              </label>
            ))}
          </fieldset>
        )}
        {error !== null && (
          <p className="region-error" role="alert">
            {error}
          </p>
        )}
        {confirming ? (
          <fieldset className="confirm">
            <legend className="visually-hidden">Confirm</legend>
            <p>{ONLY_COPY}</p>
            <div className="actions">
              <button
                type="button"
                className="button button-danger"
                disabled={busy}
                onClick={() => {
                  setConfirming(false)
                  onAnswer(toAnswer(item, 'discard', ''))
                }}
              >
                Yes, discard it
              </button>
              <button type="button" className="button" onClick={() => setConfirming(false)}>
                Keep it
              </button>
            </div>
          </fieldset>
        ) : (
          <div className="actions">
            {kind === 'unlock' ? (
              <button type="button" className="button button-primary" onClick={onUnlock}>
                Enter the password
              </button>
            ) : (
              <button
                type="submit"
                className="button button-primary"
                disabled={!ready || busy}
                aria-describedby={!ready ? reasonId : undefined}
              >
                {label}
              </button>
            )}
            {!ready && kind !== 'unlock' && (
              <span className="hint why-disabled" id={reasonId}>
                {missing}
              </span>
            )}
            {several && (
              <button
                type="button"
                className="button"
                disabled={!ready || busy}
                onClick={() => value !== null && onAnswerMany(value)}
              >
                Answer all
              </button>
            )}
            {onSkip !== null && (
              <button type="button" className="button" onClick={onSkip}>
                Skip for now
              </button>
            )}
          </div>
        )}
      </form>
      {radios && question.options.length > 1 && (
        <p className="hint keys-hint">
          Press 1 to {Math.min(question.options.length, 9)} to choose, Enter to file, S to skip.
        </p>
      )}
    </div>
  )
}

function isRadio(target: EventTarget | null): boolean {
  return target instanceof HTMLInputElement && target.type === 'radio'
}

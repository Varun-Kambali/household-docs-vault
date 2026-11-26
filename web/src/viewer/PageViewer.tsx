// The viewer: the pages of one document as images, stacked and centred, with the cited lines
// outlined, and the stored fields beside them. Pages load as they come into view. The address is
// the state: /doc/:id?page=2&lines=3,4 (the page from 1, the lines as the API counts them).
import { useEffect, useRef, useState } from 'react'

import type { DocumentOut } from '../api/types.ts'
import { navigate } from '../app/location.ts'
import { Region } from '../app/Region.tsx'
import { hrefFor } from '../app/route.ts'
import { CARD_NOTE, isCard, isMasked, typeLabel } from '../common/labels.ts'
import { Masked } from '../common/Masked.tsx'
import { useInView } from '../common/useInView.ts'
import { useLines } from '../common/useLines.ts'
import { useReveal } from '../common/useReveal.ts'
import { Outlines } from './Outlines.tsx'
import { parseLines } from './lines.ts'
import { useDocument } from './useDocument.ts'

type Size = 'fit' | 'actual'

function label(name: string): string {
  const spaced = name.replace(/_/g, ' ')
  return spaced.charAt(0).toUpperCase() + spaced.slice(1)
}

function shown(value: unknown): string {
  if (Array.isArray(value)) return value.map(shown).join(', ')
  if (value !== null && typeof value === 'object') return JSON.stringify(value)
  return String(value)
}

function isTyping(target: EventTarget | null): boolean {
  return (
    target instanceof HTMLElement &&
    (target.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName))
  )
}

function Page({
  id,
  index,
  total,
  size,
  current,
  outlined,
  onOutline,
}: {
  id: string
  index: number
  total: number
  size: Size
  current: boolean
  outlined: number[]
  onOutline: (idx: number) => void
}) {
  const { ref, seen } = useInView<HTMLDivElement>()
  const [failed, setFailed] = useState(false)
  const load = seen || current
  const lines = useLines(load && outlined.length > 0 ? id : null, index)
  const boxes = lines.boxes.filter((line) => outlined.includes(line.idx))
  return (
    <div
      ref={ref}
      className="page-frame viewer-page"
      data-testid={`page-${index + 1}`}
      data-size={size}
      data-current={current}
    >
      {!load ? null : failed ? (
        <p className="region-empty">This page cannot be shown.</p>
      ) : (
        <>
          <img
            src={`/v1/documents/${encodeURIComponent(id)}/pages/${index}.png?width=${size === 'fit' ? 1200 : 1600}`}
            alt={`Page ${index + 1} of ${total}`}
            onError={() => setFailed(true)}
          />
          <Outlines
            outlines={boxes.map((line) => ({ idx: line.idx, bbox: line.bbox, text: line.text }))}
            onOpen={onOutline}
          />
        </>
      )}
    </div>
  )
}

function Fields({ doc }: { doc: DocumentOut }) {
  const entries = Object.entries(doc.fields).filter(([, value]) => value !== null && value !== '')
  if (entries.length === 0) return <p className="hint">No fields were read from this file.</p>
  return (
    <dl className="fields">
      {entries.map(([name, value]) => (
        <div key={name} className="field">
          <dt>{label(name)}</dt>
          <dd className={doc.field_kinds[name] === 'identifier' ? 'identifier' : undefined}>
            {isMasked(doc.doc_type, name) ? (
              <Masked value={shown(value)} label={label(name).toLowerCase()} />
            ) : (
              shown(value)
            )}
          </dd>
        </div>
      ))}
    </dl>
  )
}

export function PageViewer({
  id,
  page,
  lines,
}: {
  id: string
  page: number
  lines: string | null
}) {
  const loaded = useDocument(id)
  const { state: revealed, reveal } = useReveal()
  const [size, setSize] = useState<Size>('fit')
  const root = useRef<HTMLDivElement>(null)
  const total = loaded.state === 'full' ? Math.max(loaded.doc.page_count, 1) : 1
  const current = Math.min(Math.max(page, 1), total)
  const outlined = parseLines(lines)

  // On opening, and on a move to another page, the page (or the first cited line) comes into view.
  useEffect(() => {
    if (loaded.state !== 'full') return
    const target =
      root.current?.querySelector('.outline') ??
      root.current?.querySelector(`[data-testid="page-${current}"]`)
    target?.scrollIntoView?.({ block: 'center' })
  }, [loaded.state, current])

  useEffect(() => {
    function go(next: number): void {
      const target = Math.min(Math.max(next, 1), total)
      if (target === current) return
      navigate(hrefFor({ name: 'doc', id, page: target, lines: null }), { replace: true })
    }
    function onKey(event: KeyboardEvent): void {
      if (isTyping(event.target) || event.metaKey || event.ctrlKey || event.altKey) return
      if (event.key === 'ArrowRight' || event.key === 'j') go(current + 1)
      else if (event.key === 'ArrowLeft' || event.key === 'k') go(current - 1)
      else if (event.key === 'Escape') {
        if (window.history.length > 1) window.history.back()
        else navigate('/')
      }
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [current, total, id])

  const title = loaded.state === 'full' ? typeLabel(loaded.doc.doc_type) : 'Document'
  return (
    <>
      <h1 tabIndex={-1}>{title}</h1>
      <Region
        state={loaded.state}
        what="the document"
        error={loaded.state === 'error' ? loaded.error : undefined}
      >
        {loaded.state === 'full' && (
          <div className="viewer" ref={root}>
            <div className="viewer-pages">
              {Array.from({ length: total }, (_, index) => (
                <Page
                  key={index}
                  id={id}
                  index={index}
                  total={total}
                  size={size}
                  current={index + 1 === current}
                  outlined={index + 1 === current ? outlined : []}
                  onOutline={(idx) =>
                    navigate(hrefFor({ name: 'doc', id, page: current, lines: String(idx) }), {
                      replace: true,
                    })
                  }
                />
              ))}
            </div>
            <aside className="inspector" aria-label="About this file">
              <p className="inspector-path">{loaded.doc.rel_path}</p>
              <p className="hint">
                Page {current} of {total}
              </p>
              {isCard(loaded.doc.doc_type) && <p className="hint">{CARD_NOTE}</p>}
              <div className="size-control" role="radiogroup" aria-label="Page size">
                {(
                  [
                    ['fit', 'Fit width'],
                    ['actual', '100%'],
                  ] as const
                ).map(([value, text]) => (
                  <label key={value} className="size-option">
                    <input
                      type="radio"
                      name="size"
                      checked={size === value}
                      onChange={() => setSize(value)}
                    />
                    <span>{text}</span>
                  </label>
                ))}
              </div>
              <div className="actions">
                <button
                  type="button"
                  className="button"
                  onClick={() => reveal(loaded.doc.id, loaded.doc.drive_path)}
                >
                  Show in folder
                </button>
                <a
                  className="button"
                  href={`/v1/documents/${encodeURIComponent(loaded.doc.id)}/file`}
                  download
                >
                  Download original
                </a>
              </div>
              {revealed.kind === 'ok' && <output className="reveal-note">{revealed.text}</output>}
              {revealed.kind === 'error' && (
                <p className="region-error" role="alert">
                  {revealed.text}
                </p>
              )}
              <Fields doc={loaded.doc} />
            </aside>
          </div>
        )}
      </Region>
    </>
  )
}

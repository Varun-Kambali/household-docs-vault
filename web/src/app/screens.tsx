import { useEffect, useRef } from 'react'

import { AREAS, type AreaId } from './areas.ts'
import { navigate } from './location.ts'
import { Region } from './Region.tsx'
import { hrefFor } from './route.ts'

export function SearchScreen({ q, focusTick }: { q: string; focusTick: number }) {
  const box = useRef<HTMLInputElement>(null)
  // On opening, and whenever / or Cmd+K is pressed on this screen.
  useEffect(() => {
    box.current?.focus()
    // oxlint-disable-next-line react/exhaustive-effect-dependencies
  }, [focusTick])
  return (
    <>
      <h1 tabIndex={-1}>Search</h1>
      <input
        ref={box}
        className="prompt"
        type="search"
        name="q"
        autoComplete="off"
        aria-label="Ask about your documents"
        placeholder="Kavita's health policy"
        value={q}
        onChange={(event) =>
          navigate(hrefFor({ name: 'search', q: event.target.value }), { replace: true })
        }
        onKeyDown={(event) => {
          if (event.key === 'Escape' && q !== '') navigate('/', { replace: true })
        }}
      />
      <p className="hint">Ask in a few words. Name a person, a kind of document or a date.</p>
    </>
  )
}

export function InboxScreen({ waiting, error }: { waiting: number | null; error: string | null }) {
  const known = waiting !== null
  return (
    <>
      <h1 tabIndex={-1}>Inbox</h1>
      <Region
        state={
          error !== null ? 'error' : known && waiting > 0 ? 'full' : known ? 'empty' : 'loading'
        }
        error={error ?? undefined}
        what="the Inbox"
        empty="Nothing waiting. New files are read as they arrive."
      >
        <p>{waiting} waiting for an answer.</p>
      </Region>
    </>
  )
}

export function AreaScreen({ area }: { area: AreaId }) {
  const label = AREAS.find((a) => a.id === area)?.label ?? area
  // Task 35 fills in the list; until then every area is empty.
  return (
    <>
      <h1 tabIndex={-1}>{label}</h1>
      <Region state="empty" empty={`Nothing filed under ${label} yet.`} />
    </>
  )
}

export function DocScreen({ id }: { id: string }) {
  return <h1 tabIndex={-1}>Document {id}</h1>
}

export function NotFoundScreen() {
  return (
    <>
      <h1 tabIndex={-1}>Page not found</h1>
      <p>
        <a href="/">Go to Search</a>
      </p>
    </>
  )
}

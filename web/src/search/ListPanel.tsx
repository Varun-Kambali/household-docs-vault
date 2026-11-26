// A list on a screen: the sentence over it, then the rows, with the four states drawn (loading,
// error, empty, full). Used by the search screen and by every area page.
import { Region } from '../app/Region.tsx'
import { Sentence } from './Sentence.tsx'
import { ListResults } from './ListResults.tsx'
import { fromQuery } from './listQuery.ts'
import type { ListState } from './useList.ts'

export function ListPanel({
  list,
  people,
  empty,
}: {
  list: ListState
  people: ReadonlyMap<string, string>
  empty: string
}) {
  const { view } = list
  if (list.unreadable) {
    return (
      <section className="list" aria-label="List">
        <p className="region-error" role="alert">
          This link holds a list the app can't read.
        </p>
        <p>
          <a href="/">Start a new search</a>
        </p>
      </section>
    )
  }
  if (view === null) {
    return (
      <Region
        state={list.error !== null ? 'error' : 'loading'}
        what="the list"
        error={list.error ?? undefined}
      />
    )
  }
  const query = fromQuery(view.query)
  return (
    <section className="list" aria-label="List" aria-busy={list.updating}>
      <Sentence
        sentence={view.sentence}
        query={query}
        unread={query.unread}
        updating={list.updating}
        onChange={list.change}
      />
      {list.changeError !== null && (
        <p className="region-error" role="alert">
          {list.changeError}
        </p>
      )}
      <Region state={view.rows.length === 0 ? 'empty' : 'full'} empty={empty}>
        <ListResults rows={view.rows} role={query.role} people={people} />
      </Region>
    </section>
  )
}

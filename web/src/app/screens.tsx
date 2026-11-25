import { AREAS, type AreaId } from './areas.ts'
import { Region } from './Region.tsx'

export { SearchPage as SearchScreen } from '../search/SearchPage.tsx'

// onChanged is for the Inbox list to call when an answer changes it (Task 36), so the sidebar
// number is read again then and not on every move between screens.
export function InboxScreen({
  waiting,
  error,
}: {
  waiting: number | null
  error: string | null
  onChanged: () => void
}) {
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

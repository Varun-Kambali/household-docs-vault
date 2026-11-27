import { AREAS, type AreaId } from './areas.ts'
import { usePeople } from '../common/usePeople.ts'
import { ListPanel } from '../search/ListPanel.tsx'
import { type ListQuery, areaList, listKey } from '../search/listQuery.ts'
import { useList } from '../search/useList.ts'
import { navigate } from './location.ts'
import { hrefFor } from './route.ts'

export { SearchPage as SearchScreen } from '../search/SearchPage.tsx'

export { InboxPage as InboxScreen } from '../inbox/InboxPage.tsx'

export function AreaScreen({ area, list }: { area: AreaId; list?: ListQuery }) {
  const label = AREAS.find((a) => a.id === area)?.label ?? area
  const people = usePeople()
  const whole = areaList(area)
  const source = list ?? whole
  const key = listKey(source)
  const state = useList({
    source,
    scope: key,
    seed: null,
    // Back to the area with nothing narrowed is the bare path.
    onApplied: (query) =>
      navigate(
        hrefFor(
          listKey(query) === listKey(whole)
            ? { name: 'area', area }
            : { name: 'area', area, list: query },
        ),
      ),
  })
  return (
    <>
      <h1 tabIndex={-1}>{label}</h1>
      <ListPanel
        list={state}
        people={people}
        empty={
          key === listKey(whole) ? `Nothing filed under ${label} yet.` : 'No documents match this.'
        }
      />
    </>
  )
}

export { PageViewer as DocScreen } from '../viewer/PageViewer.tsx'

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

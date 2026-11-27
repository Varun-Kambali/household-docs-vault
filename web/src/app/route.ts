// The address is the state: which screen, and what is on it. Plain History API, no router package.
import { type ListQuery, listFromParams, listParams } from '../search/listQuery.ts'
import { type AreaId, isAreaId } from './areas.ts'

export type Route =
  // A search is a prompt, or (once a list has been narrowed, or linked to) the list's own query.
  | { name: 'search'; q: string; list?: ListQuery }
  // `field` is the stored field an answer came from, marked in the viewer's list.
  | { name: 'doc'; id: string; page: number; lines: string | null; field?: string }
  | { name: 'inbox' }
  | { name: 'area'; area: AreaId; list?: ListQuery }
  | { name: 'notfound' }

export function parseRoute(pathname: string, search: string): Route {
  const params = new URLSearchParams(search)
  const parts = pathname.split('/').filter((part) => part !== '')
  const [head, tail] = parts
  if (parts.length === 0) {
    const list = listFromParams(params)
    return { name: 'search', q: params.get('q') ?? '', ...(list !== null && { list }) }
  }
  if (parts.length === 1 && head === 'inbox') return { name: 'inbox' }
  if (parts.length === 2 && head === 'doc' && tail !== undefined) {
    const page = Number(params.get('page'))
    const field = params.get('field')
    return {
      name: 'doc',
      id: tail,
      page: Number.isInteger(page) && page > 0 ? page : 0,
      lines: params.get('lines'),
      ...(field !== null && /^[a-z][a-z0-9_]{0,63}$/.test(field) && { field }),
    }
  }
  if (parts.length === 2 && head === 'area' && tail !== undefined && isAreaId(tail)) {
    const list = listFromParams(params)
    return { name: 'area', area: tail, ...(list !== null && { list }) }
  }
  return { name: 'notfound' }
}

export function hrefFor(route: Route): string {
  switch (route.name) {
    case 'search': {
      const query = route.list !== undefined ? listParams(route.list) : new URLSearchParams()
      if (route.list === undefined && route.q !== '') query.set('q', route.q)
      return query.size > 0 ? `/?${query.toString()}` : '/'
    }
    case 'inbox':
      return '/inbox'
    case 'area':
      return route.list !== undefined
        ? `/area/${route.area}?${listParams(route.list).toString()}`
        : `/area/${route.area}`
    case 'doc': {
      const query = new URLSearchParams()
      if (route.page > 0) query.set('page', String(route.page))
      if (route.lines !== null) query.set('lines', route.lines)
      if (route.field !== undefined) query.set('field', route.field)
      return `/doc/${encodeURIComponent(route.id)}${query.size > 0 ? `?${query.toString()}` : ''}`
    }
    case 'notfound':
      return '/'
  }
}

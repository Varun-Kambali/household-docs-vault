// The address is the state: which screen, and what is on it. Plain History API, no router package.
import { type AreaId, isAreaId } from './areas.ts'

export type Route =
  | { name: 'search'; q: string }
  | { name: 'doc'; id: string; page: number; lines: string | null }
  | { name: 'inbox' }
  | { name: 'area'; area: AreaId }
  | { name: 'notfound' }

export function parseRoute(pathname: string, search: string): Route {
  const params = new URLSearchParams(search)
  const parts = pathname.split('/').filter((part) => part !== '')
  const [head, tail] = parts
  if (parts.length === 0) return { name: 'search', q: params.get('q') ?? '' }
  if (parts.length === 1 && head === 'inbox') return { name: 'inbox' }
  if (parts.length === 2 && head === 'doc' && tail !== undefined) {
    const page = Number(params.get('page'))
    return {
      name: 'doc',
      id: tail,
      page: Number.isInteger(page) && page > 0 ? page : 0,
      lines: params.get('lines'),
    }
  }
  if (parts.length === 2 && head === 'area' && tail !== undefined && isAreaId(tail)) {
    return { name: 'area', area: tail }
  }
  return { name: 'notfound' }
}

export function hrefFor(route: Route): string {
  switch (route.name) {
    case 'search': {
      const query = new URLSearchParams()
      if (route.q !== '') query.set('q', route.q)
      return query.size > 0 ? `/?${query.toString()}` : '/'
    }
    case 'inbox':
      return '/inbox'
    case 'area':
      return `/area/${route.area}`
    case 'doc': {
      const query = new URLSearchParams()
      if (route.page > 0) query.set('page', String(route.page))
      if (route.lines !== null) query.set('lines', route.lines)
      return `/doc/${encodeURIComponent(route.id)}${query.size > 0 ? `?${query.toString()}` : ''}`
    }
    case 'notfound':
      return '/'
  }
}

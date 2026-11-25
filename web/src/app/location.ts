// The browser's address as a store, so a screen re-renders when it changes (a link, the back
// button, or a screen rewriting its own query).
import { useSyncExternalStore } from 'react'

import { type Route, parseRoute } from './route.ts'

const CHANGED = 'vault:locationchange'

function subscribe(onChange: () => void): () => void {
  window.addEventListener('popstate', onChange)
  window.addEventListener(CHANGED, onChange)
  return () => {
    window.removeEventListener('popstate', onChange)
    window.removeEventListener(CHANGED, onChange)
  }
}

// One string for the whole address: a snapshot must be the same value until it really changes.
const snapshot = (): string => window.location.pathname + window.location.search

export function navigate(href: string, options: { replace?: boolean } = {}): void {
  if (href === snapshot()) return
  if (options.replace) window.history.replaceState(null, '', href)
  else window.history.pushState(null, '', href)
  window.dispatchEvent(new Event(CHANGED))
}

export function useRoute(): Route {
  const address = useSyncExternalStore(subscribe, snapshot)
  const [pathname = '/', search = ''] = splitAddress(address)
  return parseRoute(pathname, search)
}

function splitAddress(address: string): [string, string] {
  const at = address.indexOf('?')
  return at === -1 ? [address, ''] : [address.slice(0, at), address.slice(at)]
}

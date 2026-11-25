// A region that loads data has four states: loading, empty, error and full. This draws the first
// three in one way, so every screen says the same thing in the same place.
import type { ReactNode } from 'react'

type Props = {
  state: 'loading' | 'empty' | 'error' | 'full'
  what?: string
  empty?: string
  error?: string
  children?: ReactNode
}

export function Region({ state, what = 'this', empty, error, children }: Props) {
  if (state === 'loading') {
    return (
      <output className="region-loading">
        <span className="skeleton" aria-hidden="true" />
        <span className="skeleton skeleton-short" aria-hidden="true" />
        <span className="region-note">Loading {what}</span>
      </output>
    )
  }
  if (state === 'empty') return <p className="region-empty">{empty}</p>
  if (state === 'error') {
    return (
      <p className="region-error" role="alert">
        {error}
      </p>
    )
  }
  return <>{children}</>
}

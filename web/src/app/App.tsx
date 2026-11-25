import { useEffect, useRef, useState, type MouseEvent } from 'react'

import { AREAS } from './areas.ts'
import { navigate, useRoute } from './location.ts'
import { AreaScreen, DocScreen, InboxScreen, NotFoundScreen, SearchScreen } from './screens.tsx'
import { useInboxCount } from './useInboxCount.ts'

function isTyping(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false
  return target.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName)
}

// A link that moves inside the page. A click with a modifier, or a middle click, is left to the
// browser, so "open in a new tab" still works.
function Link({
  href,
  current,
  children,
  onGo,
}: {
  href: string
  current: boolean
  children: React.ReactNode
  onGo: () => void
}) {
  function go(event: MouseEvent<HTMLAnchorElement>): void {
    if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey)
      return
    event.preventDefault()
    navigate(href)
    onGo()
  }
  return (
    <a className="nav-link" href={href} aria-current={current ? 'page' : undefined} onClick={go}>
      {children}
    </a>
  )
}

export function App() {
  const route = useRoute()
  const [menuOpen, setMenuOpen] = useState(false)
  const [focusTick, setFocusTick] = useState(0)
  const { count: waiting, error: waitingError, refresh } = useInboxCount()
  const main = useRef<HTMLElement>(null)
  const firstRoute = useRef(true)

  // After moving to another screen, the keyboard starts at its title. Search takes the focus itself.
  const screen =
    route.name === 'area'
      ? `area/${route.area}`
      : route.name === 'doc'
        ? `doc/${route.id}`
        : route.name
  useEffect(() => {
    if (firstRoute.current) {
      firstRoute.current = false
      return
    }
    if (screen !== 'search') main.current?.querySelector('h1')?.focus()
  }, [screen])

  useEffect(() => {
    function onKey(event: KeyboardEvent): void {
      if (event.key === 'Escape') setMenuOpen(false)
      const quick =
        (event.key === '/' && !isTyping(event.target)) ||
        (event.key === 'k' && (event.metaKey || event.ctrlKey))
      if (!quick) return
      event.preventDefault()
      navigate('/')
      setFocusTick((tick) => tick + 1)
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [])

  const close = () => setMenuOpen(false)
  const inbox = waiting !== null && waiting > 0 ? `Inbox ${waiting}` : 'Inbox'

  return (
    <div className="shell">
      <a className="skip" href="#main">
        Skip to the page
      </a>
      <header className="topbar">
        <button
          type="button"
          className="button menu-button"
          aria-expanded={menuOpen}
          aria-controls="places"
          onClick={() => setMenuOpen((open) => !open)}
        >
          Menu
        </button>
        <span className="brand">Household vault</span>
      </header>
      <nav id="places" className="sidebar" aria-label="Vault" data-open={menuOpen}>
        <ul className="nav-list">
          <li>
            <Link href="/" current={route.name === 'search'} onGo={close}>
              Search
            </Link>
          </li>
          <li>
            <Link href="/inbox" current={route.name === 'inbox'} onGo={close}>
              {inbox}
            </Link>
          </li>
        </ul>
        <ul className="nav-list nav-areas">
          {AREAS.map((area) => (
            <li key={area.id}>
              <Link
                href={`/area/${area.id}`}
                current={route.name === 'area' && route.area === area.id}
                onGo={close}
              >
                {area.label}
              </Link>
            </li>
          ))}
        </ul>
      </nav>
      <main id="main" ref={main} className="main">
        {route.name === 'search' && <SearchScreen q={route.q} focusTick={focusTick} />}
        {route.name === 'inbox' && <InboxScreen waiting={waiting} error={waitingError} onChanged={refresh} />}
        {route.name === 'area' && <AreaScreen area={route.area} />}
        {route.name === 'doc' && <DocScreen id={route.id} />}
        {route.name === 'notfound' && <NotFoundScreen />}
      </main>
    </div>
  )
}

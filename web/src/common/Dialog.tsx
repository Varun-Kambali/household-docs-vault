// A native <dialog> for the steps that ask for a password: a focused step, closed by Escape, with
// the focus put back on the button that opened it, and on its first field again when content loads in. Its contents exist only while it is open, so
// whatever was typed in it is gone when it closes.
import { useEffect, useId, useRef, type ReactNode } from 'react'

const FIELDS = 'input:not([type=hidden]), select, textarea, button'

export function Dialog({
  open,
  title,
  onClose,
  children,
}: {
  open: boolean
  title: string
  onClose: () => void
  children: ReactNode
}) {
  const ref = useRef<HTMLDialogElement>(null)
  const titleId = useId()

  useEffect(() => {
    const dialog = ref.current
    if (!open || dialog === null) return
    const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null
    // jsdom (the tests) has no showModal; the attribute is the same state.
    if (typeof dialog.showModal === 'function') dialog.showModal()
    else dialog.setAttribute('open', '')
    dialog.querySelector<HTMLElement>(FIELDS)?.focus()
    // Contents that load after it opened (a status read, say) get the focus when they appear,
    // unless the person is already on one of them.
    const watcher = new MutationObserver(() => {
      const on = document.activeElement
      if (on !== null && on !== dialog && dialog.contains(on)) return
      dialog.querySelector<HTMLElement>(FIELDS)?.focus()
    })
    watcher.observe(dialog, { childList: true, subtree: true })
    return () => {
      watcher.disconnect()
      if (typeof dialog.close === 'function') dialog.close()
      else dialog.removeAttribute('open')
      const back = opener?.isConnected ? opener : document.querySelector<HTMLElement>('main h1')
      back?.focus()
    }
  }, [open])

  return (
    <dialog
      ref={ref}
      className="dialog"
      aria-labelledby={titleId}
      onCancel={(event) => {
        event.preventDefault()
        onClose()
      }}
      onKeyDown={(event) => {
        if (event.key !== 'Escape') return
        event.preventDefault()
        event.stopPropagation()
        onClose()
      }}
    >
      {open && (
        <div className="dialog-body">
          <h2 id={titleId}>{title}</h2>
          {children}
        </div>
      )}
    </dialog>
  )
}

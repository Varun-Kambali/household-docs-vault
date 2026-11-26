// True once an element has come into view (and stays true): a page image loads when it is
// about to be seen. Where there is no IntersectionObserver the element counts as seen.
import { useEffect, useRef, useState } from 'react'

export function useInView<T extends Element>(): { ref: React.RefObject<T | null>; seen: boolean } {
  const ref = useRef<T | null>(null)
  const [seen, setSeen] = useState(typeof IntersectionObserver === 'undefined')
  useEffect(() => {
    const element = ref.current
    if (seen || element === null) return
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) setSeen(true)
      },
      { rootMargin: '400px 0px' },
    )
    observer.observe(element)
    return () => observer.disconnect()
  }, [seen])
  return { ref, seen }
}

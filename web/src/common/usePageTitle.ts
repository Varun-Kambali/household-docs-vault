// The tab, the History menu and a screen reader announcing a move all use the page's title to say
// where you are, so every screen sets it. A prompt in a title has its card numbers masked.
import { useEffect } from 'react'

import { maskCards } from './maskCards.ts'

export const SITE = 'Household vault'

export function usePageTitle(part: string | null): void {
  useEffect(() => {
    if (part !== null) document.title = `${maskCards(part)} - ${SITE}`
  }, [part])
}

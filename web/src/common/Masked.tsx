// An ID number: the last four digits and dots, and a Show button. Once shown it stays shown until
// the screen gives it a new key (a new answer). The timed reveal for secrets comes in M4.
import { useState } from 'react'

import { lastFour } from './labels.ts'

export function Masked({ value, label }: { value: string; label: string }) {
  const [shown, setShown] = useState(false)
  return (
    <span className="masked">
      <span className="identifier">{shown ? value : lastFour(value)}</span>
      <button type="button" className="link-button" onClick={() => setShown((now) => !now)}>
        {shown ? `Hide ${label}` : `Show ${label}`}
      </button>
    </span>
  )
}

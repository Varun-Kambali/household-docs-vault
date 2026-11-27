// A plain bar with words. It does not move except to a new value: no pulsing, no spinner.
import type { ProgressOut } from '../api/types.ts'

function words(progress: ProgressOut): string {
  const { total_in_batch: total, done_in_batch: done, current } = progress
  if (current !== null) return `Reading ${Math.min(done + 1, total)} of ${total}`
  const asked = progress.asked_in_batch
  const needs = asked === 0 ? '' : `. ${asked} ${asked === 1 ? 'needs' : 'need'} a look.`
  return `Read ${done} of ${total}${needs}`
}

export function Progress({ progress }: { progress: ProgressOut | null }) {
  if (progress === null || progress.total_in_batch === 0) return null
  const text = words(progress)
  const reading = progress.current !== null
  return (
    <div className="progress">
      <p className="progress-words">{text}</p>
      <progress aria-label={text} max={progress.total_in_batch} value={progress.done_in_batch} />
      {reading && <p className="hint progress-file">{progress.current}</p>}
    </div>
  )
}

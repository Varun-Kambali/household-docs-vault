// The words for each step the activity log records, and for a time as it is read in a list.
const STEPS: Record<string, string> = {
  noticed: 'Found',
  checked: 'Checked',
  read: 'Read',
  filed: 'Filed',
  needs_a_look: 'Needs a look',
  waiting: 'Waiting',
  undone: 'Undone',
  answered: 'Answered',
  discarded: 'Discarded',
  kept_both: 'Kept both',
  unlocked: 'Unlocked',
  secrets: 'Secrets',
  gone: 'Gone',
  retried: 'Tried again',
  error: 'Problem',
}

export function stepLabel(step: string): string {
  return STEPS[step] ?? step.replace(/_/g, ' ')
}

const WHEN = new Intl.DateTimeFormat('en-IN', {
  day: 'numeric',
  month: 'short',
  hour: 'numeric',
  minute: '2-digit',
})

export function formatWhen(iso: string): string {
  const at = new Date(iso)
  return Number.isNaN(at.getTime()) ? iso : WHEN.format(at)
}

const DAY = new Intl.DateTimeFormat('en-IN', { day: 'numeric', month: 'short' })
const CLOCK = new Intl.DateTimeFormat('en-IN', { hour: 'numeric', minute: '2-digit' })

// The activity list shows the day once as a heading and the clock time on each row.
export function formatDay(iso: string): string {
  const at = new Date(iso)
  return Number.isNaN(at.getTime()) ? iso : DAY.format(at)
}

// The local calendar day as YYYY-MM-DD: a key and an HTML id, which cannot hold a space.
const DAY_KEY = new Intl.DateTimeFormat('en-CA', {
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
})

export function dayKey(iso: string): string {
  const at = new Date(iso)
  return Number.isNaN(at.getTime()) ? iso.replace(/\s+/g, '-') : DAY_KEY.format(at)
}

export function formatClock(iso: string): string {
  const at = new Date(iso)
  return Number.isNaN(at.getTime()) ? iso : CLOCK.format(at)
}

// "Kavita Rao/Health/2026-09-20 Prescription.pdf" is filed in "Kavita Rao / Health".
export function whereFiled(path: string | null): string | null {
  if (path === null) return null
  const folders = path.split('/').slice(0, -1)
  return folders.length === 0 ? null : folders.join(' / ')
}

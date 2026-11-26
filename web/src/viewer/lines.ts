// The `lines` of a viewer address: line numbers as the API counts them (from 0), as a list or
// ranges ("3", "3,5", "2-4"). Anything that is not a line is dropped, and a range is capped.
const MAX_LINES = 200

export function parseLines(value: string | null): number[] {
  if (value === null) return []
  const found: number[] = []
  for (const part of value.split(',')) {
    const match = /^(\d+)(?:-(\d+))?$/.exec(part.trim())
    if (match === null) continue
    const from = Number(match[1])
    const to = match[2] === undefined ? from : Number(match[2])
    for (let idx = from; idx <= to && found.length < MAX_LINES; idx += 1) found.push(idx)
  }
  return found
}

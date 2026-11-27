// Where the app says it was unsure, in words: what it was unsure of, for each reason that means
// doubt. A reason that is certain (a locked file, a duplicate) has no entry and no "Not sure:" line.
const DOUBT: Record<string, string> = {
  person_unsure: 'the name on it',
  type_unsure: 'what kind of document it is',
  no_english: 'what kind of document it is',
  field_issue: 'a value on it',
  missing_required: 'a value that is needed',
  read_failed: 'how to read it',
  card_unreadable: 'the card photo',
  possible_copy: 'whether it is a copy of a file already kept',
}

export function doubtOf(reasons: string[]): string | null {
  const found = reasons.map((reason) => DOUBT[reason]).find((what) => what !== undefined)
  return found ?? null
}

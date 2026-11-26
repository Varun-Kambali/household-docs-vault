// A part of a prompt the API could not read comes back as a phrase with the kind first
// ("date: before Diwali", "person: Anil"). The screen says the words alone.
export function unreadWords(phrase: string): string {
  return phrase.replace(/^[a-z]+: /, '')
}

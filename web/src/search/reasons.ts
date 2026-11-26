import type { NoAnswerOut } from '../api/types.ts'

export function reasonSentence(reason: NoAnswerOut['reason'], unread: string[]): string {
  switch (reason) {
    case 'unknown_person':
      return unread[0] !== undefined
        ? `No one called ${unread[0]} is in the household.`
        : 'No one by that name is in the household.'
    case 'weak_match':
      return 'Nothing matches closely enough to answer from.'
    case 'no_field':
      return 'I found the file but not that detail on it.'
    case 'not_on_page':
      return 'I could not find that detail on the page, so I will not guess it.'
    case 'no_documents':
      return 'No file matches that.'
  }
}

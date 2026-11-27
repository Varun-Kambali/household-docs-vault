// A prompt is not a place for a card number. A run of 13 to 19 digits that passes Luhn (spaces or
// dashes allowed between digits) keeps only its last four, so it never reaches the address bar,
// the browser history or a link. The server masks again before the models see the prompt.
const RUN = /(?<!\d)\d(?:[ -]?\d){12,18}(?!\d)/g

function luhn(digits: string): boolean {
  let sum = 0
  for (let i = 0; i < digits.length; i += 1) {
    let n = Number(digits[digits.length - 1 - i])
    if (i % 2 === 1) {
      n *= 2
      if (n > 9) n -= 9
    }
    sum += n
  }
  return sum % 10 === 0
}

export function maskCards(text: string): string {
  return text.replace(RUN, (hit) => {
    const digits = hit.replace(/\D/g, '')
    return luhn(digits) ? `•••• ${digits.slice(-4)}` : hit
  })
}

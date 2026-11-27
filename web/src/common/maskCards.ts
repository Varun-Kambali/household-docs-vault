// A prompt is not a place for a card number. A card-shaped run of 13 to 19 digits (spaces, dashes,
// dots or slashes between digits) keeps only its last four, so it never reaches the address bar,
// the browser history or a link. Card-shaped means Luhn-valid with the length and leading digits
// of a card brand, so an IMEI or a long policy number stays whole. The server masks again before
// the models see the prompt (api/search.py, same ranges).
const RUN = /(?<!\d)\d(?:[ .\-/]?\d){12,18}(?!\d)/g

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

const within = (digits: string, size: number, low: number, high: number): boolean => {
  const lead = Number(digits.slice(0, size))
  return lead >= low && lead <= high
}

function cardShaped(digits: string): boolean {
  if (!luhn(digits)) return false
  const n = digits.length
  const two = digits.slice(0, 2)
  return (
    (digits[0] === '4' && (n === 13 || n === 16 || n === 19)) || // Visa
    (n === 16 && (within(digits, 2, 51, 55) || within(digits, 4, 2221, 2720))) || // Mastercard
    (n === 15 && (two === '34' || two === '37')) || // American Express
    (n === 16 && (['60', '65', '81', '82'].includes(two) || digits.startsWith('508'))) || // RuPay
    (n >= 16 &&
      n <= 19 &&
      (digits.startsWith('6011') || two === '65' || within(digits, 3, 644, 649))) || // Discover
    (n >= 14 && n <= 19 && (two === '36' || two === '38' || within(digits, 3, 300, 305))) || // Diners
    (n >= 16 && n <= 19 && within(digits, 4, 3528, 3589)) // JCB
  )
}

export function maskCards(text: string): string {
  return text.replace(RUN, (hit) => {
    const digits = hit.replace(/\D/g, '')
    return cardShaped(digits) ? `•••• ${digits.slice(-4)}` : hit
  })
}

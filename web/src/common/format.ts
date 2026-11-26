// A stored value as the answer writes it: the same rules as format_amount and format_date in
// search/answer.py (Indian grouping and "Rs" for amounts, "19 Sep 2027" for dates). Anything that
// cannot be read is shown as stored, and identifiers and text are never touched.
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

function indian(digits: string): string {
  if (digits.length <= 3) return digits
  const tail = digits.slice(-3)
  let head = digits.slice(0, -3)
  const groups: string[] = []
  while (head.length > 2) {
    groups.unshift(head.slice(-2))
    head = head.slice(0, -2)
  }
  return [head, ...groups, tail].filter((part) => part !== '').join(',')
}

export function formatAmount(value: unknown): string {
  const text = String(value).trim()
  const plain = text.replace(/^(?:rs\.?|inr|₹)\s*/i, '').replace(/,/g, '')
  const match = /^(\d+)(?:\.(\d+))?$/.exec(plain)
  if (match === null) return text
  let whole = BigInt(match[1] ?? '0')
  const fraction = match[2] ?? ''
  let paise = Number((fraction + '00').slice(0, 2))
  // Rounded half up at the second decimal, as the answer does.
  if (Number(fraction.charAt(2) || '0') >= 5) paise += 1
  if (paise === 100) {
    whole += 1n
    paise = 0
  }
  return `Rs ${indian(whole.toString())}${paise === 0 ? '' : `.${String(paise).padStart(2, '0')}`}`
}

export function formatDate(value: unknown): string {
  const text = String(value).trim()
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(text)
  if (match === null) return text
  const [year, month, day] = [Number(match[1]), Number(match[2]), Number(match[3])]
  const real = new Date(Date.UTC(year, month - 1, day))
  if (
    real.getUTCFullYear() !== year ||
    real.getUTCMonth() !== month - 1 ||
    real.getUTCDate() !== day
  )
    return text
  return `${day} ${MONTHS[month - 1]} ${year}`
}

export function formatField(kind: string | undefined, value: unknown): string {
  if (Array.isArray(value)) return value.map((item) => formatField(kind, item)).join(', ')
  if (value !== null && typeof value === 'object') return JSON.stringify(value)
  if (kind === 'amount') return formatAmount(value)
  if (kind === 'date') return formatDate(value)
  return String(value)
}

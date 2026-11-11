/**
 * Display formatting for widget values.
 *
 * Percentages are fractions (0.934 is 93.4%), so SQL can return a ratio
 * without multiplying. Months and dates are ISO strings from the warehouse,
 * read as UTC so a `2026-01-01` never displays as December in the Americas.
 */
export type ValueFormat = 'text' | 'number' | 'compact' | 'currency' | 'currencyCompact' | 'percent' | 'month' | 'date'

const number = new Intl.NumberFormat('en-US', { maximumFractionDigits: 1 })
const compact = new Intl.NumberFormat('en-US', { notation: 'compact', maximumFractionDigits: 1 })
const currency = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 })
// Significant digits rather than fraction digits, so $3.97B is not rounded to $4B.
const currencyCompact = new Intl.NumberFormat('en-US', {
  style: 'currency',
  currency: 'USD',
  notation: 'compact',
  maximumSignificantDigits: 3,
})
const percent = new Intl.NumberFormat('en-US', { style: 'percent', maximumFractionDigits: 1 })
const month = new Intl.DateTimeFormat('en-US', { month: 'short', year: 'numeric', timeZone: 'UTC' })
const date = new Intl.DateTimeFormat('en-US', { dateStyle: 'medium', timeZone: 'UTC' })

/** A finite number, or null for null, empty, and non-numeric values. */
export function toNumber(value: unknown): number | null {
  if (value === null || value === undefined || value === '') return null
  const n = typeof value === 'number' ? value : Number(value)
  return Number.isFinite(n) ? n : null
}

function toDate(value: unknown): Date | null {
  if (typeof value !== 'string' || !value) return null
  // `YYYY-MM` (a month filter) and `YYYY-MM-DD` both parse as UTC midnight.
  const d = new Date(value.length === 7 ? `${value}-01` : value)
  return Number.isNaN(d.getTime()) ? null : d
}

export function formatValue(value: unknown, format: ValueFormat = 'text'): string {
  if (value === null || value === undefined || value === '') return '–'
  if (format === 'month' || format === 'date') {
    const d = toDate(value)
    return d ? (format === 'month' ? month : date).format(d) : String(value)
  }
  if (format === 'text') return String(value)

  const n = toNumber(value)
  if (n === null) return String(value)
  switch (format) {
    case 'number':
      return number.format(n)
    case 'compact':
      return compact.format(n)
    case 'currency':
      return currency.format(n)
    case 'currencyCompact':
      return currencyCompact.format(n)
    case 'percent':
      return percent.format(n)
  }
}

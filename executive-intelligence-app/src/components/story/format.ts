import { toNumber } from '../dashboard/format'

const wholePercent = new Intl.NumberFormat('en-US', { style: 'percent', maximumFractionDigits: 0 })

/** A fraction as a whole percent: 0.934 -> "93%". Briefings round; dashboards keep the decimal. */
export function pct(value: unknown): string {
  const n = toNumber(value)
  return n === null ? '–' : wholePercent.format(n)
}

/** A change in a fraction, as points: -0.05 -> "down 5 pts". */
export function points(change: unknown): string {
  const n = toNumber(change)
  if (n === null) return '–'
  const pts = Math.round(n * 100)
  if (pts === 0) return 'unchanged'
  return `${pts > 0 ? 'up' : 'down'} ${Math.abs(pts)} pt${Math.abs(pts) === 1 ? '' : 's'}`
}

/**
 * Money rounded as the insight records round it (`money` in data/insights.py),
 * so a figure on the page and the same figure in a sentence read alike:
 * $1.2B, $54M, $9.2M, $850K.
 */
export function money(value: unknown): string {
  const n = toNumber(value)
  if (n === null) return '–'
  const sign = n < 0 ? '-' : ''
  const a = Math.abs(n)
  if (a >= 1e9) return `${sign}$${(a / 1e9).toFixed(1)}B`
  if (a >= 1e7) return `${sign}$${Math.round(a / 1e6)}M`
  if (a >= 1e6) return `${sign}$${(a / 1e6).toFixed(1)}M`
  return `${sign}$${Math.round(a / 1e3)}K`
}

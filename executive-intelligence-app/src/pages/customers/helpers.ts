import { money } from '../../components/story'

/** Contracts that end within this many days are called out, as on the account page. */
export const RENEWAL_SOON_DAYS = 120

/** Money with its direction: "+$11M" or "−$65M". */
export function signedMoney(value: number | null | undefined): string {
  if (value == null) return '–'
  return `${value >= 0 ? '+' : '−'}${money(Math.abs(value))}`
}

/** "Master supply agreement" -> "MSA"; "Software license" stays as written. */
export function contractAbbreviation(type: string): string {
  const words = type.split(/\s+/).filter(Boolean)
  return words.length >= 3 ? words.map((w) => w[0].toUpperCase()).join('') : type
}

/** Time to a contract's end, in the unit that reads best: "72 days", "5 mo", "1.8 yrs". */
export function renewsIn(days: number | null | undefined): string {
  if (days == null) return '–'
  if (days <= RENEWAL_SOON_DAYS) return `${days} day${days === 1 ? '' : 's'}`
  if (days <= 730) return `${Math.round(days / 30.4)} mo`
  return `${(days / 365).toFixed(1)} yrs`
}
